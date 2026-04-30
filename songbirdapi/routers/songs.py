import os
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_current_user, get_db, load_settings
from ..models import User
from .. import crud

_config = load_settings()

router = APIRouter(prefix="/songs", tags=["songs"])


class SongResponse(BaseModel):
    uuid: str
    url: str
    properties: dict | None
    artwork_cached: bool = False
    owner_id: str | None = None
    root_song_id: str | None = None
    parent_song_id: str | None = None
    source: str | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _compute_artwork_cached(cls, data):
        if hasattr(data, "artwork_thumb"):
            return {
                "uuid": data.uuid,
                "url": data.url,
                "properties": data.properties,
                "artwork_cached": data.artwork_thumb is not None,
                "owner_id": data.owner_id,
                "root_song_id": getattr(data, "root_song_id", None),
                "parent_song_id": getattr(data, "parent_song_id", None),
                "source": getattr(data, "source", None),
            }
        return data


class LibrarySongResponse(SongResponse):
    added_at: str
    last_position: float
    last_played_at: str | None


class SongWithCount(BaseModel):
    uuid: str
    properties: dict | None
    count: int
    source: str | None = None
    artwork_cached: bool = False


class RecentlyPlayedSong(BaseModel):
    uuid: str
    properties: dict | None
    last_played_at: str
    artwork_cached: bool = False


class RecentlySavedSong(BaseModel):
    uuid: str
    properties: dict | None
    added_at: str
    artwork_cached: bool = False


class RecentlyAddedSong(BaseModel):
    uuid: str
    url: str
    properties: dict | None
    artwork_cached: bool = False
    added_at: str
    source: str | None = None


class ExploreResponse(BaseModel):
    most_played: list[SongWithCount]
    most_downloaded: list[SongWithCount]
    most_libraryed: list[SongWithCount]
    recently_added: list[RecentlyAddedSong]
    your_most_played: list[SongWithCount]
    your_most_downloaded: list[SongWithCount]
    your_recently_saved: list[RecentlySavedSong]
    your_recently_played: list[RecentlyPlayedSong]


@router.get("/", response_model=list[SongResponse])
async def list_songs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await crud.list_songs(db, user_id=current_user.id)


@router.get("/library", response_model=list[LibrarySongResponse])
async def list_library(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await crud.list_library_with_songs(db, current_user.id)


@router.get("/explore", response_model=ExploreResponse)
async def explore(
    window: Literal["day", "week", "all"] = "week",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    most_played = await crud.get_popular_songs(db, window, user_id=current_user.id)
    most_downloaded = await crud.get_popular_downloads(
        db, window, user_id=current_user.id
    )
    most_libraryed = await crud.get_most_libraryed(db, window, user_id=current_user.id)
    recently_added_songs = await crud.get_recently_added(
        db, user_id=current_user.id, window=window
    )
    your_most_played = await crud.get_user_most_played(db, current_user.id, window)
    your_most_downloaded = await crud.get_user_most_downloaded(
        db, current_user.id, window
    )
    your_recently_saved = await crud.get_user_recently_saved(
        db, current_user.id, window
    )
    your_recently_played = await crud.get_user_recently_played(
        db, current_user.id, window=window
    )
    recently_added = [
        RecentlyAddedSong(
            uuid=s.uuid,
            url=s.url,
            properties=s.properties,
            added_at=s.created_at.isoformat(),
            source=s.source,
            artwork_cached=s.artwork_thumb is not None,
        )
        for s in recently_added_songs
    ]
    return ExploreResponse(
        most_played=most_played,
        most_downloaded=most_downloaded,
        most_libraryed=most_libraryed,
        recently_added=recently_added,
        your_most_played=your_most_played,
        your_most_downloaded=your_most_downloaded,
        your_recently_saved=your_recently_saved,
        your_recently_played=your_recently_played,
    )


@router.get("/{id}", response_model=SongResponse)
async def get_song(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    song = await crud.get_song(db, id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="song not found"
        )
    return song


@router.post("/{id}/play", status_code=204)
async def record_play(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await crud.record_play(db, id, current_user.id)


@router.get("/{id}/artwork/{size}")
async def get_artwork(
    id: str,
    size: Literal["thumb", "full"] = "full",
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import RedirectResponse

    song = await crud.get_song(db, id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Song not found"
        )
    path = (
        song.artwork_thumb
        if size == "thumb"
        else (song.artwork_full or song.artwork_thumb)
    )
    if path and os.path.exists(path):
        return FileResponse(path, media_type="image/jpeg")
    itunes_url = (song.properties or {}).get("artworkUrl100", "")
    if itunes_url:
        target_size = "200x200bb" if size == "thumb" else "600x600bb"
        return RedirectResponse(
            url=itunes_url.replace("100x100bb", target_size), status_code=302
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Artwork not cached"
    )


@router.post("/{id}/artwork", status_code=200)
async def upload_artwork(
    id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    song = await crud.get_song(db, id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    if (
        song.owner_id
        and song.owner_id != current_user.id
        and current_user.role.value != "admin"
    ):
        raise HTTPException(status_code=403, detail="Forbidden")

    MAX_ARTWORK_BYTES = 10 * 1024 * 1024  # 10 MB
    if file.size is not None and file.size > MAX_ARTWORK_BYTES:
        raise HTTPException(
            status_code=413, detail="Artwork file too large (max 10 MB)"
        )
    content = await file.read()
    if len(content) > MAX_ARTWORK_BYTES:
        raise HTTPException(
            status_code=413, detail="Artwork file too large (max 10 MB)"
        )

    from ..artwork import store_artwork_from_bytes

    try:
        thumb_path, full_path = await store_artwork_from_bytes(
            id, content, _config.artwork_dir
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await crud.update_song_artwork(db, id, thumb_path, full_path)

    return {"ok": True}
