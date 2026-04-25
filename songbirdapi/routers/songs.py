from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_current_user, get_db
from ..models import User
from .. import crud

router = APIRouter(prefix="/songs", tags=["songs"])


class SongResponse(BaseModel):
    uuid: str
    url: str
    properties: dict | None

    model_config = {"from_attributes": True}


class LibrarySongResponse(SongResponse):
    added_at: str
    last_position: float
    last_played_at: str | None


class SongWithCount(BaseModel):
    uuid: str
    properties: dict | None
    count: int


class RecentlyPlayedSong(BaseModel):
    uuid: str
    properties: dict | None
    last_played_at: str


class ExploreResponse(BaseModel):
    most_played: list[SongWithCount]
    most_downloaded: list[SongWithCount]
    most_libraryed: list[SongWithCount]
    recently_added: list[SongResponse]
    your_most_played: list[SongWithCount]
    your_recently_played: list[RecentlyPlayedSong]


@router.get("/", response_model=list[SongResponse])
async def list_songs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return await crud.list_songs(db)


@router.get("/library", response_model=list[LibrarySongResponse])
async def list_library(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await crud.list_library_with_songs(db, current_user.id)


@router.post("/{id}/play", status_code=204)
async def record_play(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await crud.record_play(db, id, current_user.id)


@router.get("/explore", response_model=ExploreResponse)
async def explore(
    window: Literal["day", "week", "all"] = "week",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    most_played = await crud.get_popular_songs(db, window)
    most_downloaded = await crud.get_popular_downloads(db, window)
    most_libraryed = await crud.get_most_libraryed(db, window)
    recently_added = await crud.get_recently_added(db)
    your_most_played = await crud.get_user_most_played(db, current_user.id)
    your_recently_played = await crud.get_user_recently_played(db, current_user.id)
    return ExploreResponse(
        most_played=most_played,
        most_downloaded=most_downloaded,
        most_libraryed=most_libraryed,
        recently_added=recently_added,
        your_most_played=your_most_played,
        your_recently_played=your_recently_played,
    )
