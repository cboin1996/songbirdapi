import contextlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from songbirdapi import crud, security
from songbirdapi.models import AuthSession, Role, User
from songbirdapi.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    create_access_token,
    decode_token,
    hash_password,
    make_refresh_jwt,
    session_ids,
    verify_password,
)
from songbirdapi.settings import SongbirdServerConfig
from songbirdapi.sessions import (
    Decision,
    RevokeReason,
    decide_refresh,
    policy_from_settings,
    state_of,
)
from ..dependencies import (
    AuthContext,
    get_current_auth,
    get_current_user,
    get_db,
    load_settings,
    require_admin,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    email: str
    password: str
    role: Role = Role.user


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: Role
    is_active: bool

    model_config = {"from_attributes": True}


USER_AGENT_MAX_LEN = 256
# Dead sessions (revoked, idle or capped) are kept this long, then pruned at
# the user's next login and at startup.
PRUNE_AFTER = timedelta(days=7)


def _set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    refresh_max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=refresh_max_age,
    )


def _issue_session_cookies(
    response: Response,
    user: User,
    session: AuthSession,
    config: SongbirdServerConfig,
    now: datetime,
) -> None:
    absolute = policy_from_settings(config).absolute
    refresh_token = make_refresh_jwt(session, absolute, config.jwt_secret)
    access_token = create_access_token(
        user.id, user.role.value, session.id, config.jwt_secret
    )
    remaining = int((session.created_at + absolute - now).total_seconds())
    _set_auth_cookies(
        response,
        access_token,
        refresh_token,
        max(remaining, 0),
        config.cookie_secure,
    )


async def prune_dead_sessions(
    db: AsyncSession,
    now: datetime,
    config: SongbirdServerConfig,
    user_id: Optional[str] = None,
) -> int:
    """Delete sessions dead for over PRUNE_AFTER: of one user at login, of
    everyone at startup. The caller commits."""
    policy = policy_from_settings(config)
    return await crud.prune_auth_sessions(
        db,
        revoked_before=now - PRUNE_AFTER,
        idle_before=now - policy.idle - PRUNE_AFTER,
        created_before=now - policy.absolute - PRUNE_AFTER,
        user_id=user_id,
    )


def _new_jti() -> str:
    return secrets.token_urlsafe(16)


def _new_session(user: User, request: Request, now: datetime) -> AuthSession:
    user_agent = request.headers.get("user-agent")
    return AuthSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        jti=_new_jti(),
        created_at=now,
        last_used_at=now,
        rotated_at=now,
        user_agent=user_agent[:USER_AGENT_MAX_LEN] if user_agent else None,
    )


@router.post("/login")
async def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await crud.get_user_by_username(db, body.username)
    if not user or not await verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )

    # Take the user's lock before saving anything, then check again: a password
    # change or disable that landed while we were verifying must win.
    verified_hash = user.hashed_password
    locked = await crud.lock_user(db, user.id)
    if locked is None or locked.hashed_password != verified_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not locked.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )

    config = load_settings()
    now = security.utcnow()
    policy = policy_from_settings(config)
    await prune_dead_sessions(db, now, config, user_id=user.id)
    # Leave room for the session this login creates.
    await crud.revoke_stalest_auth_sessions(
        db,
        user.id,
        keep=config.session_max_per_user - 1,
        now=now,
        idle_since=now - policy.idle,
        created_since=now - policy.absolute,
        reason=RevokeReason.CAP,
    )
    session = await crud.create_auth_session(db, _new_session(user, request, now))
    _issue_session_cookies(response, user, session, config, now)
    return UserResponse.model_validate(user)


# Logout accepts an access token this long past its expiry, so a tab left open
# overnight still signs out on the server, but a leaked token from weeks ago
# cannot sign the victim out.
LOGOUT_ACCESS_LEEWAY = timedelta(hours=24)


def _session_claims(
    token: str, secret: str, token_type: str, leeway: timedelta = timedelta(0)
) -> Optional[tuple[str, str]]:
    """(user_id, sid) from a correctly signed token of `token_type`."""
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM], leeway=leeway)
    except jwt.PyJWTError:
        return None
    return session_ids(payload, token_type)


@router.post("/logout")
async def logout(
    response: Response,
    access_token: Optional[str] = Cookie(default=None),
    refresh_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Always 200 and always clears the cookies. Revokes the session named by
    the refresh cookie, or by the access cookie only when there is no refresh
    cookie at all."""
    config = load_settings()
    if refresh_token is not None:
        claims = _session_claims(refresh_token, config.jwt_secret, "refresh")
    elif access_token is not None:
        claims = _session_claims(
            access_token, config.jwt_secret, "access", LOGOUT_ACCESS_LEEWAY
        )
    else:
        claims = None
    if claims:
        user_id, sid = claims
        try:
            await crud.revoke_auth_session(
                db, sid, user_id, security.utcnow(), reason=RevokeReason.LOGOUT
            )
        except Exception:
            logger.exception("logout: could not revoke session %s", sid)
            with contextlib.suppress(Exception):
                await db.rollback()
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(
            name, httponly=True, samesite="lax", secure=config.cookie_secure
        )
    return {"message": "logged out"}


@router.post("/refresh")
async def refresh(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
    )
    if not refresh_token:
        raise credentials_exception
    config = load_settings()
    # Only token errors are 401. Anything else (the DB being down) must surface
    # as a 5xx so the client treats it as "unavailable" and keeps the session.
    try:
        payload = decode_token(refresh_token, config.jwt_secret)
    except jwt.PyJWTError:
        raise credentials_exception
    ids, jti = session_ids(payload, "refresh"), payload.get("jti")
    # Tokens from before sessions existed carry no sid: sign in again.
    if ids is None or not jti:
        raise credentials_exception
    user_id, sid = ids

    user = await crud.get_user(db, user_id)
    if not user or not user.is_active:
        raise credentials_exception
    session = await crud.lock_auth_session(db, sid)
    if session is None or session.user_id != user.id:
        raise credentials_exception

    now = security.utcnow()
    decision = decide_refresh(state_of(session), jti, now, policy_from_settings(config))
    if decision is Decision.EXPIRED:
        raise credentials_exception
    if decision is Decision.REUSE:
        # Commits before raising: the request session rolls back on teardown.
        await crud.revoke_auth_session(db, sid, user.id, now, reason=RevokeReason.REUSE)
        logger.warning(
            "refresh token reuse: revoked session %s for user %s", sid, user.id
        )
        raise credentials_exception
    if decision is Decision.ROTATE:
        session.prev_jti = session.jti
        session.jti = _new_jti()
        session.rotated_at = now
    elif decision is Decision.BRANCH:
        if jti not in (session.jti, session.prev_jti):
            logger.warning(
                "refresh token reuse with detection off: branched session %s for user %s",
                sid,
                user.id,
            )
        session.jti = _new_jti()
        session.rotated_at = now
    session.last_used_at = now
    await db.commit()

    _issue_session_cookies(response, user, session, config, now)
    return {"message": "token refreshed"}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> UserResponse:
    if await crud.get_user_by_username(db, body.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already taken"
        )
    if await crud.get_user_by_email(db, body.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = User(
        id=str(uuid.uuid4()),
        username=body.username,
        email=body.email,
        hashed_password=await hash_password(body.password),
        role=body.role,
    )
    await crud.create_user(db, user)
    return UserResponse.model_validate(user)


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.patch("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordBody,
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
):
    # Lock first: a login in flight either finishes before this (and is revoked
    # below) or waits and finds the new password.
    current_user = await crud.lock_user(db, auth.user.id) or auth.user
    if not await verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password"
        )
    # Revoke every session, this one included: a thief holding a copy of this
    # device's cookies shares its session. The caller gets a fresh one. Password,
    # revocation and the new session land in one commit.
    config = load_settings()
    now = security.utcnow()
    current_user.hashed_password = await hash_password(body.new_password)
    await crud.revoke_user_auth_sessions(
        db, current_user.id, now, reason=RevokeReason.PASSWORD
    )
    session = _new_session(current_user, request, now)
    db.add(session)
    await db.commit()
    _issue_session_cookies(response, current_user, session, config, now)
