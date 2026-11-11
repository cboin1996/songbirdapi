"""Refresh-token session rules.

Pure decision logic for rotating refresh tokens with reuse detection. The
route does the locking, I/O and cookies; everything that decides what a
presented refresh token means lives here so it can be tested with literal
times. See the session-lifetime spec for the rules and why they exist.
"""

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .models import AuthSession
    from .settings import SongbirdServerConfig


class RevokeReason(str, enum.Enum):
    """Why a session was revoked, stored in auth_sessions.revoke_reason."""

    LOGOUT = "logout"
    PASSWORD = "password"
    REUSE = "reuse"
    CAP = "cap"
    DISABLED = "disabled"


class Decision(enum.Enum):
    EXPIRED = "expired"
    HOLD = "hold"
    ROTATE = "rotate"
    REPLAY = "replay"
    BRANCH = "branch"
    REUSE = "reuse"


@dataclass(frozen=True)
class RefreshPolicy:
    idle: timedelta
    absolute: timedelta
    replay_window: timedelta
    reuse_detection: bool


@dataclass(frozen=True)
class SessionState:
    jti: str
    prev_jti: Optional[str]
    created_at: datetime
    last_used_at: datetime
    rotated_at: datetime
    revoked_at: Optional[datetime]


def decide_refresh(
    state: SessionState, presented_jti: str, now: datetime, policy: RefreshPolicy
) -> Decision:
    if (
        state.revoked_at is not None
        or now - state.last_used_at > policy.idle
        or now > state.created_at + policy.absolute
    ):
        return Decision.EXPIRED
    within_window = now - state.rotated_at <= policy.replay_window
    if presented_jti == state.jti:
        return Decision.HOLD if within_window else Decision.ROTATE
    if presented_jti == state.prev_jti:
        return Decision.REPLAY if within_window else Decision.BRANCH
    return Decision.REUSE if policy.reuse_detection else Decision.BRANCH


def policy_from_settings(config: "SongbirdServerConfig") -> RefreshPolicy:
    return RefreshPolicy(
        idle=timedelta(days=config.session_idle_days),
        absolute=timedelta(days=config.session_absolute_days),
        replay_window=timedelta(seconds=config.refresh_replay_window_seconds),
        reuse_detection=config.refresh_reuse_detection,
    )


def state_of(row: "AuthSession") -> SessionState:
    return SessionState(
        jti=row.jti,
        prev_jti=row.prev_jti,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        rotated_at=row.rotated_at,
        revoked_at=row.revoked_at,
    )
