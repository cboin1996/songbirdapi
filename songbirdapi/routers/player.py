from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..database import get_db
from ..dependencies import get_current_user
from ..models import RepeatMode, User

router = APIRouter(prefix="/player", tags=["player"])


class PlayerState(BaseModel):
    shuffle: bool
    repeat: Literal['off', 'one', 'all']
    queue: list[str]
    queue_index: int
    shuffle_order: list[int] | None = None


def _serialize(state) -> PlayerState:
    return PlayerState(
        shuffle=state.shuffle,
        repeat=state.repeat.value,
        queue=state.queue,
        queue_index=state.queue_index,
        shuffle_order=state.shuffle_order,
    )


@router.get("/state", response_model=PlayerState)
async def get_state(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    state = await crud.get_player_state(db, current_user.id)
    if state is None:
        return PlayerState(shuffle=False, repeat='off', queue=[], queue_index=-1)
    return _serialize(state)


@router.put("/state", response_model=PlayerState)
async def update_state(
    body: PlayerState,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    state = await crud.upsert_player_state(
        db, current_user.id,
        body.shuffle,
        RepeatMode(body.repeat),
        body.queue,
        body.queue_index,
        body.shuffle_order,
    )
    return _serialize(state)
