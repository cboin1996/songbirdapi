from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from .. import crud
from ..dependencies import get_current_user, get_db
from ..models import User

router = APIRouter(prefix="/playlists", tags=["playlists"])


class PlaylistResponse(BaseModel):
    id: str
    name: str
    icon: str | None = None
    created_at: datetime
    updated_at: datetime
    song_count: int = 0


class CreatePlaylistBody(BaseModel):
    name: str
    icon: str | None = None


class RenamePlaylistBody(BaseModel):
    name: str
    icon: str | None = None


class AddSongBody(BaseModel):
    song_uuid: str


class ReorderBody(BaseModel):
    song_uuids: list[str]


class BulkAddSongsBody(BaseModel):
    song_uuids: list[str]


class BulkRemoveSongsBody(BaseModel):
    song_uuids: list[str]


@router.get("", response_model=list[PlaylistResponse])
async def list_playlists(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    playlists = await crud.list_playlists(db, current_user.id)
    results = []
    for pl in playlists:
        songs = await crud.get_playlist_songs(db, pl.id)
        results.append(PlaylistResponse(
            id=pl.id, name=pl.name, icon=pl.icon,
            created_at=pl.created_at, updated_at=pl.updated_at,
            song_count=len(songs),
        ))
    return results


@router.post("", response_model=PlaylistResponse, status_code=status.HTTP_201_CREATED)
async def create_playlist(
    body: CreatePlaylistBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pl = await crud.create_playlist(db, current_user.id, body.name.strip() or "untitled", body.icon)
    return PlaylistResponse(id=pl.id, name=pl.name, icon=pl.icon, created_at=pl.created_at, updated_at=pl.updated_at)


@router.patch("/{playlist_id}", response_model=PlaylistResponse)
async def rename_playlist(
    playlist_id: str,
    body: RenamePlaylistBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pl = await crud.get_playlist(db, playlist_id)
    if not pl or pl.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Playlist not found")
    pl = await crud.rename_playlist(db, playlist_id, body.name, body.icon)
    songs = await crud.get_playlist_songs(db, playlist_id)
    return PlaylistResponse(id=pl.id, name=pl.name, icon=pl.icon, created_at=pl.created_at, updated_at=pl.updated_at, song_count=len(songs))


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(
    playlist_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pl = await crud.get_playlist(db, playlist_id)
    if not pl or pl.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Playlist not found")
    await crud.delete_playlist(db, playlist_id)


@router.get("/{playlist_id}/songs")
async def get_playlist_songs(
    playlist_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pl = await crud.get_playlist(db, playlist_id)
    if not pl or pl.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Playlist not found")
    songs = await crud.get_playlist_songs(db, playlist_id)
    return [
        {
            "uuid": s.uuid,
            "url": s.url,
            "properties": s.properties,
            "artwork_cached": s.artwork_thumb is not None,
            "owner_id": s.owner_id,
        }
        for s in songs
    ]


@router.post("/{playlist_id}/songs", status_code=status.HTTP_204_NO_CONTENT)
async def add_song_to_playlist(
    playlist_id: str,
    body: AddSongBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pl = await crud.get_playlist(db, playlist_id)
    if not pl or pl.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Playlist not found")
    song = await crud.get_song(db, body.song_uuid)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    # Allow community songs, songs the user owns, or songs in their library
    # (duplicate-detection adds other users' songs to your library).
    if song.owner_id is not None and song.owner_id != current_user.id:
        entry = await crud.get_library_entry(db, current_user.id, body.song_uuid)
        if not entry:
            raise HTTPException(status_code=404, detail="Song not found")
    ok = await crud.add_song_to_playlist(db, playlist_id, body.song_uuid)
    if not ok:
        raise HTTPException(status_code=409, detail="Song already in playlist")


@router.post("/{playlist_id}/songs/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_add_songs_to_playlist(
    playlist_id: str,
    body: BulkAddSongsBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not body.song_uuids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="song_uuids must not be empty")
    pl = await crud.get_playlist(db, playlist_id)
    if not pl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")
    if pl.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    await crud.bulk_add_songs_to_playlist(db, playlist_id, body.song_uuids)


@router.delete("/{playlist_id}/songs/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_remove_songs_from_playlist(
    playlist_id: str,
    body: BulkRemoveSongsBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not body.song_uuids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="song_uuids must not be empty")
    pl = await crud.get_playlist(db, playlist_id)
    if not pl or pl.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Playlist not found")
    await crud.bulk_remove_songs_from_playlist(db, playlist_id, body.song_uuids)


@router.delete("/{playlist_id}/songs/{song_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_song_from_playlist(
    playlist_id: str,
    song_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pl = await crud.get_playlist(db, playlist_id)
    if not pl or pl.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Playlist not found")
    await crud.remove_song_from_playlist(db, playlist_id, song_uuid)


@router.patch("/{playlist_id}/songs", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_playlist_songs(
    playlist_id: str,
    body: ReorderBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pl = await crud.get_playlist(db, playlist_id)
    if not pl or pl.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Playlist not found")
    await crud.reorder_playlist(db, playlist_id, body.song_uuids)
