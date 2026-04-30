from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..database import get_db
from ..dependencies import get_current_user
from ..models import User

router = APIRouter(prefix="/library/offline", tags=["offline"])


class SyncRequest(BaseModel):
    song_ids: list[str]


class SyncResponse(BaseModel):
    server_only: list[str]


@router.get("", response_model=list[str])
async def get_offline_songs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await crud.get_offline_song_ids(db, current_user.id)


@router.post("/sync", response_model=SyncResponse)
async def sync_offline_songs(
    body: SyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    server_only = await crud.sync_offline_songs(db, current_user.id, body.song_ids)
    return SyncResponse(server_only=server_only)


@router.post("/{song_id}", status_code=204)
async def add_offline_song(
    song_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await crud.add_offline_song(db, current_user.id, song_id)


@router.delete("/{song_id}", status_code=204)
async def remove_offline_song(
    song_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await crud.remove_offline_song(db, current_user.id, song_id)


@router.delete("", status_code=204)
async def clear_offline_songs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await crud.clear_offline_songs(db, current_user.id)
