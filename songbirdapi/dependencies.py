from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from . import crud
from .database import get_db as get_db
from . import security
from .models import AuthSession, Role, User
from .security import decode_token, session_ids
from .sessions import policy_from_settings
from .settings import SongbirdServerConfig


def process_song_url(url: str):
    return url.split("&list")[0]


def load_settings() -> SongbirdServerConfig:
    return SongbirdServerConfig()  # pyright: ignore


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


async def get_current_auth(
    access_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )
    if not access_token:
        raise credentials_exception
    config = load_settings()
    try:
        payload = decode_token(access_token, config.jwt_secret)
    except jwt.PyJWTError:
        raise credentials_exception
    # Tokens from before sessions existed carry no sid: the client refreshes,
    # that fails too, and the user signs in again.
    ids = session_ids(payload, "access")
    if ids is None:
        raise credentials_exception
    user_id, sid = ids

    found = await crud.get_user_and_session(db, user_id, sid)
    if found is None:
        raise credentials_exception
    user, session = found
    # Idle is enforced on refresh; an access token is at most 15 min old.
    absolute = policy_from_settings(config).absolute
    if (
        not user.is_active
        or session.revoked_at is not None
        or security.utcnow() > session.created_at + absolute
    ):
        raise credentials_exception
    return AuthContext(user=user, session=session)


async def get_current_user(auth: AuthContext = Depends(get_current_auth)) -> User:
    return auth.user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != Role.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return current_user
