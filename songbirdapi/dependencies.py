from typing import Optional

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from . import crud
from .database import get_db as get_db
from .models import Role, User
from .security import decode_token
from .settings import SongbirdServerConfig


def process_song_url(url: str):
    return url.split("&list")[0]


def load_settings() -> SongbirdServerConfig:
    return SongbirdServerConfig()  # pyright: ignore


async def get_current_user(
    access_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )
    if not access_token:
        raise credentials_exception
    config = load_settings()
    try:
        payload = decode_token(access_token, config.jwt_secret)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user = await crud.get_user(db, user_id)
    if not user or not user.is_active:
        raise credentials_exception
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != Role.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
