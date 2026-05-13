from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..database import get_db
from ..dependencies import get_current_user
from ..models import AudioFormat, User

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    audio_format: AudioFormat


class SettingsUpdate(BaseModel):
    audio_format: AudioFormat


@router.get("", response_model=SettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await crud.get_user_settings(db, current_user.id)
    return SettingsResponse(audio_format=row.audio_format)


@router.put("", response_model=SettingsResponse)
async def update_settings(
    body: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await crud.update_user_settings(db, current_user.id, body.audio_format)
    return SettingsResponse(audio_format=row.audio_format)
