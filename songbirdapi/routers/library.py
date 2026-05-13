from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..crud import _is_publish_eligible
from ..database import get_db
from ..dependencies import get_current_user
from ..models import Song, SongEditDraft, User, UserSong

router = APIRouter(prefix="/library", tags=["library"])


class LibraryEntry(BaseModel):
    song_id: str
    added_at: str
    last_position: float
    last_played_at: str | None


class PositionUpdate(BaseModel):
    position: float


class BulkRemoveRequest(BaseModel):
    song_ids: list[str]


class PublishRequest(BaseModel):
    song_ids: list[str]


REQUIRED_FIELDS = [
    "trackName",
    "artistName",
    "collectionName",
    "artworkUrl100",
    "primaryGenreName",
]
FIELD_LABELS = {
    "trackName": "track name",
    "artistName": "artist",
    "collectionName": "album",
    "artworkUrl100": "artwork",
    "primaryGenreName": "genre",
}


class EligibleSong(BaseModel):
    uuid: str
    properties: dict | None
    eligible: bool
    missing_fields: list[str]
    artwork_cached: bool = False


@router.get("", response_model=list[LibraryEntry])
async def get_library(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    entries = await crud.get_library(db, current_user.id)
    return [
        LibraryEntry(
            song_id=e.song_id,
            added_at=e.added_at.isoformat(),
            last_position=e.last_position,
            last_played_at=e.last_played_at.isoformat() if e.last_played_at else None,
        )
        for e in entries
    ]


@router.get("/eligible", response_model=list[EligibleSong])
async def get_eligible_songs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Song.uuid, Song.properties, Song.artwork_thumb)
        .join(UserSong, Song.uuid == UserSong.song_id)
        .where(
            UserSong.user_id == current_user.id,
            Song.owner_id == current_user.id,
        )
    )
    songs = []
    for uuid, props, artwork_thumb in result.all():
        p = props or {}
        missing = []
        for f in REQUIRED_FIELDS:
            if f == "artworkUrl100":
                if not p.get(f) and artwork_thumb is None:
                    missing.append(FIELD_LABELS[f])
            elif not p.get(f):
                missing.append(FIELD_LABELS[f])
        songs.append(
            EligibleSong(
                uuid=uuid,
                properties=props,
                eligible=len(missing) == 0,
                missing_fields=missing,
                artwork_cached=artwork_thumb is not None,
            )
        )
    return songs


@router.post("/publish")
async def publish_songs(
    body: PublishRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    # Only publish songs owned by the current user
    result = await db.execute(
        select(Song).where(
            Song.owner_id == current_user.id, Song.uuid.in_(body.song_ids)
        )
    )
    songs = list(result.scalars().all())
    if not songs:
        return {"published": 0}

    # Clean up edit chains before publishing
    for song in songs:
        if song.parent_song_id and song.root_song_id:
            cur = song.parent_song_id
            root = song.root_song_id
            while cur and cur != root:
                intermediate = await crud.get_song(db, cur)
                if not intermediate:
                    break
                next_id = intermediate.parent_song_id
                if (
                    await crud.library_ref_count(db, cur) == 0
                    and await crud.child_ref_count(db, cur, exclude=song.uuid) == 0
                ):
                    await crud.delete_song(db, cur)
                cur = next_id

    ids = [s.uuid for s in songs]
    root_ids = [s.root_song_id for s in songs if s.root_song_id]
    draft_ids = list(set(ids + root_ids))
    await db.execute(delete(SongEditDraft).where(SongEditDraft.song_id.in_(draft_ids)))
    await db.execute(
        update(Song)
        .where(Song.uuid.in_(ids))
        .values(
            owner_id=None,
            source="community",
            parent_song_id=None,
            root_song_id=None,
        )
    )
    await db.commit()
    return {"published": len(ids)}


@router.post(
    "/{song_id}", status_code=status.HTTP_201_CREATED, response_model=LibraryEntry
)
async def add_to_library(
    song_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    song = await crud.get_song(db, song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Song not found"
        )
    entry = await crud.add_to_library(db, current_user.id, song_id)
    return LibraryEntry(
        song_id=entry.song_id,
        added_at=entry.added_at.isoformat(),
        last_position=entry.last_position,
        last_played_at=(
            entry.last_played_at.isoformat() if entry.last_played_at else None
        ),
    )


@router.delete("/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_remove_from_library(
    body: BulkRemoveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.song_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="song_ids must not be empty"
        )
    await crud.bulk_remove_from_library(db, current_user.id, body.song_ids)


@router.delete("/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_library(
    song_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    removed = await crud.remove_from_library(db, current_user.id, song_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not in library"
        )


class RestoreRequest(BaseModel):
    target: str


@router.post("/{song_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_song(
    song_id: str,
    body: RestoreRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    song = await crud.get_song(db, song_id)
    if not song or song.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Song not found"
        )
    target = await crud.get_song(db, body.target)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Target not found"
        )

    await crud.remove_from_library(db, current_user.id, song_id)
    await crud.add_to_library(db, current_user.id, body.target)

    # Walk from current song up to target, deleting orphaned intermediates
    cur = song_id
    while cur and cur != body.target:
        s = await crud.get_song(db, cur)
        if not s:
            break
        next_id = s.parent_song_id
        if (
            await crud.library_ref_count(db, cur) == 0
            and await crud.child_ref_count(db, cur) == 0
        ):
            await crud.delete_song(db, cur)
        cur = next_id

    # Clean draft on source only — target's draft preserves edit state for the editor
    await db.execute(
        delete(SongEditDraft).where(
            SongEditDraft.user_id == current_user.id,
            SongEditDraft.song_id == song_id,
        )
    )
    await db.commit()


@router.patch("/{song_id}/position", response_model=LibraryEntry)
async def update_position(
    song_id: str,
    body: PositionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    entry = await crud.update_position(db, current_user.id, song_id, body.position)
    if not entry:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return LibraryEntry(
        song_id=entry.song_id,
        added_at=entry.added_at.isoformat(),
        last_position=entry.last_position,
        last_played_at=(
            entry.last_played_at.isoformat() if entry.last_played_at else None
        ),
    )
