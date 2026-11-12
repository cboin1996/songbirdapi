from datetime import datetime, timedelta, timezone

import pytest

from songbirdapi.sessions import Decision, RefreshPolicy, SessionState, decide_refresh

LOGIN = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
POLICY = RefreshPolicy(
    idle=timedelta(days=30),
    absolute=timedelta(days=90),
    replay_window=timedelta(seconds=60),
    reuse_detection=True,
)


def _state(
    rotated_at=LOGIN,
    last_used_at=None,
    created_at=LOGIN,
    revoked_at=None,
    jti="cur",
    prev_jti="prev",
):
    return SessionState(
        jti=jti,
        prev_jti=prev_jti,
        created_at=created_at,
        last_used_at=last_used_at or rotated_at,
        rotated_at=rotated_at,
        revoked_at=revoked_at,
    )


def test_current_token_after_replay_window_rotates():
    now = LOGIN + timedelta(seconds=61)
    assert decide_refresh(_state(), "cur", now, POLICY) is Decision.ROTATE


@pytest.mark.parametrize("seconds", [0, 60])
def test_current_token_within_replay_window_is_held(seconds):
    now = LOGIN + timedelta(seconds=seconds)
    assert decide_refresh(_state(), "cur", now, POLICY) is Decision.HOLD


@pytest.mark.parametrize("seconds", [0, 60])
def test_previous_token_within_replay_window_replays(seconds):
    now = LOGIN + timedelta(seconds=seconds)
    assert decide_refresh(_state(), "prev", now, POLICY) is Decision.REPLAY


def test_previous_token_after_replay_window_branches():
    now = LOGIN + timedelta(seconds=61)
    assert decide_refresh(_state(), "prev", now, POLICY) is Decision.BRANCH


@pytest.mark.parametrize("seconds", [0, 61])
def test_older_token_is_reuse(seconds):
    now = LOGIN + timedelta(seconds=seconds)
    assert decide_refresh(_state(), "older", now, POLICY) is Decision.REUSE


def test_first_token_of_a_session_has_no_previous_and_unknown_is_reuse():
    state = _state(prev_jti=None)
    assert decide_refresh(state, "older", LOGIN, POLICY) is Decision.REUSE


def test_reuse_with_detection_off_branches():
    policy = RefreshPolicy(
        idle=timedelta(days=30),
        absolute=timedelta(days=90),
        replay_window=timedelta(seconds=60),
        reuse_detection=False,
    )
    now = LOGIN + timedelta(seconds=5)
    assert decide_refresh(_state(), "older", now, policy) is Decision.BRANCH


def test_two_quick_refreshes_then_the_oldest_token_is_not_reuse():
    # Login issues t0. A refresh 2 min later rotates to t1 (prev=t0). A
    # refresh with t1 5 s later is held, so the state stays (t1, prev=t0)
    # and a straggler still carrying t0 replays instead of revoking.
    state = _state(jti="t1", prev_jti="t0", rotated_at=LOGIN + timedelta(minutes=2))
    held = LOGIN + timedelta(minutes=2, seconds=5)
    assert decide_refresh(state, "t1", held, POLICY) is Decision.HOLD
    straggler = LOGIN + timedelta(minutes=2, seconds=8)
    assert decide_refresh(state, "t0", straggler, POLICY) is Decision.REPLAY


def test_idle_exactly_30_days_still_refreshes():
    now = LOGIN + timedelta(days=30)
    assert decide_refresh(_state(), "cur", now, POLICY) is Decision.ROTATE


def test_idle_past_30_days_is_expired():
    now = LOGIN + timedelta(days=30, seconds=1)
    assert decide_refresh(_state(), "cur", now, POLICY) is Decision.EXPIRED


def test_absolute_exactly_90_days_still_refreshes():
    now = LOGIN + timedelta(days=90)
    state = _state(rotated_at=now - timedelta(days=1))
    assert decide_refresh(state, "cur", now, POLICY) is Decision.ROTATE


def test_absolute_past_90_days_is_expired_even_when_active():
    now = LOGIN + timedelta(days=90, seconds=1)
    state = _state(rotated_at=now - timedelta(minutes=5))
    assert decide_refresh(state, "cur", now, POLICY) is Decision.EXPIRED


def test_idle_is_measured_from_last_use_not_last_rotation():
    # A held refresh bumps last_used_at without rotating.
    state = _state(last_used_at=LOGIN + timedelta(days=20))
    now = LOGIN + timedelta(days=45)
    assert decide_refresh(state, "cur", now, POLICY) is Decision.ROTATE


@pytest.mark.parametrize("presented", ["cur", "prev", "older"])
def test_revoked_session_is_expired(presented):
    state = _state(revoked_at=LOGIN + timedelta(seconds=1))
    now = LOGIN + timedelta(seconds=2)
    assert decide_refresh(state, presented, now, POLICY) is Decision.EXPIRED


@pytest.mark.parametrize("bad", [0, -1])
def test_session_max_per_user_below_one_stops_startup(bad):
    from pydantic import ValidationError

    from songbirdapi.settings import SongbirdServerConfig

    with pytest.raises(ValidationError):
        SongbirdServerConfig(api_key="k", jwt_secret="s", session_max_per_user=bad)
