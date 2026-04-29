from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..database import get_db
from ..dependencies import get_current_user
from ..models import RepeatMode, User

router = APIRouter(prefix="/player", tags=["player"])


class QueueSource(BaseModel):
    id: str
    label: str
    href: str


class PlayerState(BaseModel):
    shuffle: bool
    repeat: Literal['off', 'one', 'all']
    queue: list[str] = Field(default_factory=list, max_length=2000)
    queue_index: int
    shuffle_order: list[int] | None = None
    play_context: str | None = None
    shuffle_seed: int | None = None
    shuffle_position: int = 0
    manual_next: list[str] = Field(default_factory=list)
    current_song_uuid: str | None = None
    queue_sources: dict[str, QueueSource] = Field(default_factory=dict)


def _serialize(state) -> PlayerState:
    return PlayerState(
        shuffle=state.shuffle,
        repeat=state.repeat.value,
        queue=state.queue,
        queue_index=state.queue_index,
        shuffle_order=state.shuffle_order,
        play_context=state.play_context,
        shuffle_seed=state.shuffle_seed,
        shuffle_position=state.shuffle_position or 0,
        manual_next=state.manual_next or [],
        current_song_uuid=state.current_song_uuid,
        queue_sources=state.queue_sources or {},
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
        body.play_context,
        body.shuffle_seed,
        body.shuffle_position,
        body.manual_next,
        body.current_song_uuid,
        {k: v.model_dump() for k, v in body.queue_sources.items()},
    )
    return _serialize(state)
