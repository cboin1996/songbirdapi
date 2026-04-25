from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..database import get_db
from ..dependencies import get_current_user
from ..models import User

router = APIRouter(prefix="/library", tags=["library"])


class LibraryEntry(BaseModel):
    song_id: str
    added_at: str
    last_position: float
    last_played_at: str | None


class PositionUpdate(BaseModel):
    position: float


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


@router.post("/{song_id}", status_code=status.HTTP_201_CREATED, response_model=LibraryEntry)
async def add_to_library(
    song_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    song = await crud.get_song(db, song_id)
    if not song:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Song not found")
    entry = await crud.add_to_library(db, current_user.id, song_id)
    return LibraryEntry(
        song_id=entry.song_id,
        added_at=entry.added_at.isoformat(),
        last_position=entry.last_position,
        last_played_at=entry.last_played_at.isoformat() if entry.last_played_at else None,
    )


@router.delete("/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_library(
    song_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    removed = await crud.remove_from_library(db, current_user.id, song_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not in library")


@router.patch("/{song_id}/position", response_model=LibraryEntry)
async def update_position(
    song_id: str,
    body: PositionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    entry = await crud.update_position(db, current_user.id, song_id, body.position)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not in library")
    return LibraryEntry(
        song_id=entry.song_id,
        added_at=entry.added_at.isoformat(),
        last_position=entry.last_position,
        last_played_at=entry.last_played_at.isoformat() if entry.last_played_at else None,
    )
