import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

import bcrypt
import jwt

if TYPE_CHECKING:
    from .models import AuthSession

ACCESS_TOKEN_EXPIRE_MINUTES = 15
ALGORITHM = "HS256"


# bcrypt is intentionally CPU-heavy (~250ms per hash/verify on modern hw).
# Running it directly inside an async route blocks the event loop; under
# concurrent logins (e.g. e2e suite) the loop gets starved, sqlalchemy
# pool releases stall, and the QueuePool exhausts. Offload to a thread.
async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hash_password_sync, password)


async def verify_password(plain: str, hashed: str) -> bool:
    return await asyncio.to_thread(_verify_password_sync, plain, hashed)


def _hash_password_sync(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password_sync(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(subject: str, role: str, sid: str, secret: str) -> str:
    expire = utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": subject, "role": role, "sid": sid, "exp": expire, "type": "access"},
        secret,
        algorithm=ALGORITHM,
    )


def utcnow() -> datetime:
    """The app clock for sessions and tokens. Tests shift it forward."""
    return datetime.now(timezone.utc)


def make_refresh_jwt(session: "AuthSession", absolute: timedelta, secret: str) -> str:
    """The refresh token for a session's current jti. Built from the row so the
    claims can never disagree with it."""
    # Deterministic on purpose: no iat, fixed claim order, and exp derived
    # from the session's login time, so re-issuing a session's current token
    # (hold/replay) yields the same string and concurrent refreshes agree on
    # one cookie value.
    return jwt.encode(
        {
            "sub": session.user_id,
            "type": "refresh",
            "sid": session.id,
            "jti": session.jti,
            "exp": session.created_at + absolute,
        },
        secret,
        algorithm=ALGORITHM,
    )


def session_ids(payload: dict, token_type: str) -> Optional[tuple[str, str]]:
    """(user_id, sid) from a decoded token of `token_type`, else None. Tokens
    from before sessions existed carry no sid, so they come back None."""
    if payload.get("type") != token_type:
        return None
    user_id, sid = payload.get("sub"), payload.get("sid")
    return (user_id, sid) if user_id and sid else None


def decode_token(token: str, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=[ALGORITHM])
