"""Refresh-token rotation, replay and reuse detection over HTTP.

Time only ever moves forward from the real clock (real now + offset), so the
JWT library's own wall-clock exp check keeps passing. Idle/absolute edges are
covered by the pure rules in tests/unit/test_sessions.py.
"""

from datetime import timedelta

import pytest
from httpx import AsyncClient

from songbirdapi import security
from songbirdapi.routes import AUTH_LOGIN, AUTH_REFRESH

pytestmark = pytest.mark.asyncio(loop_scope="session")

NINETY_DAYS = 90 * 24 * 3600


class _Clock:
    def __init__(self):
        self.offset = timedelta(0)

    def advance(self, **kwargs):
        self.offset += timedelta(**kwargs)


@pytest.fixture
def clock(monkeypatch):
    real = security.utcnow
    c = _Clock()
    monkeypatch.setattr(security, "utcnow", lambda: real() + c.offset)
    return c


def _set_cookie_attrs(resp, name: str) -> dict:
    """Parse one Set-Cookie line for `name` into {attr_lower: value}."""
    for line in resp.headers.get_list("set-cookie"):
        first, *attrs = [p.strip() for p in line.split(";")]
        key, _, value = first.partition("=")
        if key == name:
            parsed = {"value": value}
            for a in attrs:
                k, _, v = a.partition("=")
                parsed[k.lower()] = v
            return parsed
    raise AssertionError(
        f"no Set-Cookie for {name}: {resp.headers.get_list('set-cookie')}"
    )


async def _login(client: AsyncClient, user) -> dict:
    resp = await client.post(
        AUTH_LOGIN, json={"username": user.username, "password": "testpass123"}
    )
    assert resp.status_code == 200
    return {
        "access_token": resp.cookies["access_token"],
        "refresh_token": resp.cookies["refresh_token"],
    }


async def _refresh(client: AsyncClient, refresh_token: str):
    client.cookies.clear()
    return await client.post(AUTH_REFRESH, cookies={"refresh_token": refresh_token})


async def test_refresh_rotates_and_sets_both_cookies(
    test_client: AsyncClient, regular_user, clock
):
    tokens = await _login(test_client, regular_user)
    clock.advance(seconds=61)

    resp = await _refresh(test_client, tokens["refresh_token"])

    assert resp.status_code == 200
    refresh = _set_cookie_attrs(resp, "refresh_token")
    assert refresh["value"] != tokens["refresh_token"]
    # Time left to the 90-day cap: 90 d minus the 61 s already elapsed.
    assert abs(int(refresh["max-age"]) - (NINETY_DAYS - 61)) <= 2
    assert "httponly" in refresh
    assert _set_cookie_attrs(resp, "access_token")["value"]


async def test_concurrent_refresh_with_the_same_token_agrees_on_one_cookie(
    test_client: AsyncClient, fresh_user, clock
):
    tokens = await _login(test_client, fresh_user)
    clock.advance(seconds=61)

    first = await _refresh(test_client, tokens["refresh_token"])
    second = await _refresh(test_client, tokens["refresh_token"])
    assert len(await _session_rows(fresh_user)) == 1

    assert first.status_code == 200
    assert second.status_code == 200
    assert (
        _set_cookie_attrs(first, "refresh_token")["value"]
        == _set_cookie_attrs(second, "refresh_token")["value"]
    )


async def test_refresh_with_the_new_token_inside_the_window_holds(
    test_client: AsyncClient, regular_user, clock
):
    tokens = await _login(test_client, regular_user)
    clock.advance(seconds=61)
    rotated = _set_cookie_attrs(
        await _refresh(test_client, tokens["refresh_token"]), "refresh_token"
    )["value"]
    clock.advance(seconds=5)

    held = await _refresh(test_client, rotated)

    assert held.status_code == 200
    assert _set_cookie_attrs(held, "refresh_token")["value"] == rotated


async def test_late_replay_branches_and_the_unused_successor_then_revokes(
    test_client: AsyncClient, regular_user, clock
):
    tokens = await _login(test_client, regular_user)
    clock.advance(seconds=61)
    lost = _set_cookie_attrs(
        await _refresh(test_client, tokens["refresh_token"]), "refresh_token"
    )["value"]
    clock.advance(seconds=61)

    # The client never saw `lost` (dead zone) and retries with the old token.
    branched = await _refresh(test_client, tokens["refresh_token"])
    assert branched.status_code == 200
    branched_token = _set_cookie_attrs(branched, "refresh_token")["value"]
    assert branched_token not in (lost, tokens["refresh_token"])

    # Someone presenting the dead successor is reuse: the session is revoked.
    assert (await _refresh(test_client, lost)).status_code == 401
    assert (await _refresh(test_client, branched_token)).status_code == 401


async def test_reuse_revokes_the_session_for_every_token(
    test_client: AsyncClient, regular_user, clock
):
    tokens = await _login(test_client, regular_user)
    clock.advance(seconds=61)
    t1 = _set_cookie_attrs(
        await _refresh(test_client, tokens["refresh_token"]), "refresh_token"
    )["value"]
    clock.advance(seconds=61)
    t2 = _set_cookie_attrs(await _refresh(test_client, t1), "refresh_token")["value"]
    clock.advance(seconds=61)

    # t0 is two generations old: neither current nor previous.
    assert (await _refresh(test_client, tokens["refresh_token"])).status_code == 401
    # The revoke was committed, so the legitimate current token is dead too.
    assert (await _refresh(test_client, t2)).status_code == 401
    assert (await _me(test_client, tokens["access_token"])).status_code == 401


async def test_refresh_without_session_claims_is_rejected(
    test_client: AsyncClient, regular_user
):
    # Shape of a refresh token issued before sessions existed.
    from songbirdapi.dependencies import load_settings

    import jwt as pyjwt

    legacy = pyjwt.encode(
        {
            "sub": regular_user.id,
            "type": "refresh",
            "exp": security.utcnow() + timedelta(days=7),
        },
        load_settings().jwt_secret,
        algorithm=security.ALGORITHM,
    )
    assert (await _refresh(test_client, legacy)).status_code == 401


async def test_refresh_with_another_users_session_is_rejected(
    test_client: AsyncClient, regular_user, admin_user
):
    from songbirdapi.dependencies import load_settings

    import jwt as pyjwt

    admin_tokens = await _login(test_client, admin_user)
    admin_claims = pyjwt.decode(
        admin_tokens["refresh_token"],
        load_settings().jwt_secret,
        algorithms=[security.ALGORITHM],
    )
    from songbirdapi.models import AuthSession

    forged = security.make_refresh_jwt(
        AuthSession(
            id=admin_claims["sid"],
            user_id=regular_user.id,
            jti=admin_claims["jti"],
            created_at=security.utcnow(),
        ),
        timedelta(days=90),
        load_settings().jwt_secret,
    )
    assert (await _refresh(test_client, forged)).status_code == 401


async def test_refresh_lock_serialises_concurrent_requests(
    test_client: AsyncClient, regular_user, clock, monkeypatch
):
    import asyncio

    from httpx import ASGITransport

    from songbirdapi import crud
    from songbirdapi.server import app

    tokens = await _login(test_client, regular_user)
    clock.advance(seconds=61)

    real_lock = crud.lock_auth_session
    first_holds_lock = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def pausing_lock(db, sid):
        nonlocal calls
        calls += 1
        row = await real_lock(db, sid)
        if calls == 1:
            first_holds_lock.set()
            await release.wait()
        return row

    monkeypatch.setattr(crud, "lock_auth_session", pausing_lock)
    cookies = {"refresh_token": tokens["refresh_token"]}

    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as a,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as b,
    ):
        req1 = asyncio.create_task(a.post(AUTH_REFRESH, cookies=cookies))
        await asyncio.wait_for(first_holds_lock.wait(), timeout=5)
        req2 = asyncio.create_task(b.post(AUTH_REFRESH, cookies=cookies))
        await asyncio.sleep(0.5)
        # Request 2 must be stuck on the row lock while request 1 holds it.
        assert not req2.done()
        release.set()
        r1, r2 = await asyncio.wait_for(asyncio.gather(req1, req2), timeout=10)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert (
        _set_cookie_attrs(r1, "refresh_token")["value"]
        == _set_cookie_attrs(r2, "refresh_token")["value"]
    )


async def test_refresh_database_failure_is_a_server_error_not_401(
    regular_user, test_client: AsyncClient, monkeypatch
):
    from httpx import ASGITransport

    from songbirdapi import crud
    from songbirdapi.server import app

    tokens = await _login(test_client, regular_user)

    async def broken_lock(db, sid):
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(crud, "lock_auth_session", broken_lock)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            AUTH_REFRESH, cookies={"refresh_token": tokens["refresh_token"]}
        )
    assert resp.status_code == 500


# --- revocation -------------------------------------------------------------


async def _session_rows(user) -> list:
    from sqlalchemy import select

    from songbirdapi import database
    from songbirdapi.models import AuthSession

    async with database._session_factory() as db:
        result = await db.execute(
            select(AuthSession).where(AuthSession.user_id == user.id)
        )
        return list(result.scalars())


async def _only_session(user):
    (row,) = await _session_rows(user)
    return row


async def _me(client: AsyncClient, access_token: str):
    from songbirdapi.routes import AUTH_ME

    client.cookies.clear()
    return await client.get(AUTH_ME, cookies={"access_token": access_token})


async def test_logout_revokes_refresh_and_access(
    test_client: AsyncClient, regular_user
):
    from songbirdapi.routes import AUTH_LOGOUT

    tokens = await _login(test_client, regular_user)
    test_client.cookies.clear()
    resp = await test_client.post(AUTH_LOGOUT, cookies=tokens)
    assert resp.status_code == 200

    assert (await _refresh(test_client, tokens["refresh_token"])).status_code == 401
    assert (await _me(test_client, tokens["access_token"])).status_code == 401


def _access_jwt_expired(tokens: dict, ago: timedelta) -> str:
    """The access token from `tokens`, re-signed with exp `ago` in the past."""
    import jwt as pyjwt
    from datetime import datetime, timezone

    from songbirdapi.dependencies import load_settings

    secret = load_settings().jwt_secret
    claims = pyjwt.decode(
        tokens["access_token"],
        secret,
        algorithms=["HS256"],
        options={"verify_exp": False},
    )
    claims["exp"] = datetime.now(timezone.utc) - ago
    return pyjwt.encode(claims, secret, algorithm="HS256")


async def test_logout_by_recently_expired_access_token_revokes(
    test_client: AsyncClient, regular_user
):
    from songbirdapi.routes import AUTH_LOGOUT

    tokens = await _login(test_client, regular_user)
    test_client.cookies.clear()
    stale = _access_jwt_expired(tokens, timedelta(hours=1))
    resp = await test_client.post(AUTH_LOGOUT, cookies={"access_token": stale})
    assert resp.status_code == 200
    assert (await _refresh(test_client, tokens["refresh_token"])).status_code == 401


async def test_logout_ignores_an_access_token_expired_over_a_day_ago(
    test_client: AsyncClient, regular_user
):
    """A leaked, long-dead access token cannot be used to sign the victim out."""
    from songbirdapi.routes import AUTH_LOGOUT

    tokens = await _login(test_client, regular_user)
    test_client.cookies.clear()
    stale = _access_jwt_expired(tokens, timedelta(hours=25))
    resp = await test_client.post(AUTH_LOGOUT, cookies={"access_token": stale})
    assert resp.status_code == 200
    assert (await _refresh(test_client, tokens["refresh_token"])).status_code == 200


async def test_logout_ignores_the_access_token_when_a_bad_refresh_cookie_is_present(
    test_client: AsyncClient, regular_user
):
    from songbirdapi.routes import AUTH_LOGOUT

    tokens = await _login(test_client, regular_user)
    test_client.cookies.clear()
    resp = await test_client.post(
        AUTH_LOGOUT,
        cookies={"refresh_token": "not-a-jwt", "access_token": tokens["access_token"]},
    )
    assert resp.status_code == 200
    assert (await _refresh(test_client, tokens["refresh_token"])).status_code == 200


async def test_logout_clears_cookies_even_when_the_database_fails(
    test_client: AsyncClient, regular_user, monkeypatch
):
    from httpx import ASGITransport

    from songbirdapi import crud
    from songbirdapi.routes import AUTH_LOGOUT
    from songbirdapi.server import app

    tokens = await _login(test_client, regular_user)

    async def broken_revoke(*args, **kwargs):
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(crud, "revoke_auth_session", broken_revoke)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://test",
    ) as client:
        resp = await client.post(AUTH_LOGOUT, cookies=tokens)
    assert resp.status_code == 200
    for name in ("access_token", "refresh_token"):
        assert _set_cookie_attrs(resp, name)["max-age"] == "0"


async def test_logout_with_missing_or_garbage_cookies_still_succeeds(
    test_client: AsyncClient,
):
    from songbirdapi.routes import AUTH_LOGOUT

    test_client.cookies.clear()
    assert (await test_client.post(AUTH_LOGOUT)).status_code == 200
    resp = await test_client.post(
        AUTH_LOGOUT,
        cookies={"refresh_token": "not-a-jwt", "access_token": "nope"},
    )
    assert resp.status_code == 200


async def test_access_token_without_session_claim_is_rejected(
    test_client: AsyncClient, regular_user
):
    from songbirdapi.dependencies import load_settings

    import jwt as pyjwt

    legacy = pyjwt.encode(
        {
            "sub": regular_user.id,
            "role": "user",
            "type": "access",
            "exp": security.utcnow() + timedelta(minutes=15),
        },
        load_settings().jwt_secret,
        algorithm=security.ALGORITHM,
    )
    assert (await _me(test_client, legacy)).status_code == 401


async def test_password_change_signs_out_every_session_and_signs_this_device_in_again(
    test_client: AsyncClient, regular_user
):
    """A thief holding a copy of this device's cookies shares its session, so the
    caller's session is revoked too and the caller gets a fresh one."""
    from songbirdapi.routes import AUTH_PASSWORD

    phone = await _login(test_client, regular_user)
    laptop = await _login(test_client, regular_user)

    test_client.cookies.clear()
    resp = await test_client.patch(
        AUTH_PASSWORD,
        json={"current_password": "testpass123", "new_password": "testpass123"},
        cookies=laptop,
    )
    assert resp.status_code == 204
    fresh = {
        "access_token": _set_cookie_attrs(resp, "access_token")["value"],
        "refresh_token": _set_cookie_attrs(resp, "refresh_token")["value"],
    }

    for old in (phone, laptop):
        assert (await _refresh(test_client, old["refresh_token"])).status_code == 401
        assert (await _me(test_client, old["access_token"])).status_code == 401
    assert (await _me(test_client, fresh["access_token"])).status_code == 200
    assert (await _refresh(test_client, fresh["refresh_token"])).status_code == 200


async def test_login_prunes_sessions_dead_for_over_a_week(
    test_client: AsyncClient, regular_user
):
    import uuid

    from sqlalchemy import select

    from songbirdapi import database
    from songbirdapi.models import AuthSession

    now = security.utcnow()

    def row(**times):
        base = dict(created_at=now, last_used_at=now, rotated_at=now)
        base.update(times)
        return AuthSession(
            id=str(uuid.uuid4()), user_id=regular_user.id, jti="x", **base
        )

    long_revoked = row(revoked_at=now - timedelta(days=8))
    long_idle = row(last_used_at=now - timedelta(days=38))
    long_capped = row(created_at=now - timedelta(days=98))
    recently_revoked = row(revoked_at=now - timedelta(days=1))
    # Dead, but still inside the 7-day grace after the 30-day idle / 90-day cap.
    idle_in_grace = row(last_used_at=now - timedelta(days=36))
    capped_in_grace = row(created_at=now - timedelta(days=96))
    async with database._session_factory() as db:
        db.add_all(
            [
                long_revoked,
                long_idle,
                long_capped,
                recently_revoked,
                idle_in_grace,
                capped_in_grace,
            ]
        )
        await db.commit()

    await _login(test_client, regular_user)

    async with database._session_factory() as db:
        remaining = {
            s.id
            for s in (
                await db.execute(
                    select(AuthSession).where(
                        AuthSession.id.in_(
                            [
                                long_revoked.id,
                                long_idle.id,
                                long_capped.id,
                                recently_revoked.id,
                                idle_in_grace.id,
                                capped_in_grace.id,
                            ]
                        )
                    )
                )
            ).scalars()
        }
    assert remaining == {recently_revoked.id, idle_in_grace.id, capped_in_grace.id}


async def test_auth_cookies_are_secure_on_login_refresh_and_logout(
    test_client: AsyncClient, regular_user
):
    from songbirdapi.routes import AUTH_LOGOUT

    login = await test_client.post(
        AUTH_LOGIN, json={"username": regular_user.username, "password": "testpass123"}
    )
    refresh = await _refresh(test_client, login.cookies["refresh_token"])
    logout = await test_client.post(AUTH_LOGOUT)

    for resp in (login, refresh, logout):
        for name in ("access_token", "refresh_token"):
            assert "secure" in _set_cookie_attrs(resp, name), (resp.url, name)


async def test_cookie_secure_false_omits_the_flag(
    test_client: AsyncClient, regular_user, monkeypatch
):
    from songbirdapi.routes import AUTH_LOGOUT

    monkeypatch.setenv("COOKIE_SECURE", "false")

    login = await test_client.post(
        AUTH_LOGIN, json={"username": regular_user.username, "password": "testpass123"}
    )
    logout = await test_client.post(AUTH_LOGOUT)

    for resp in (login, logout):
        for name in ("access_token", "refresh_token"):
            assert "secure" not in _set_cookie_attrs(resp, name), (resp.url, name)


# --- session cap, global prune, disable ----------------------------------


@pytest.fixture
async def fresh_user():
    """A user of this test only, so sessions other tests left behind (some with
    timestamps far in the shifted future) don't count."""
    import uuid

    from songbirdapi import crud, database
    from songbirdapi.models import Role, User
    from songbirdapi.security import hash_password

    async with database._session_factory() as db:
        user = User(
            id=str(uuid.uuid4()),
            username=f"testfresh_{uuid.uuid4().hex[:6]}",
            email=f"testfresh_{uuid.uuid4().hex[:6]}@test.com",
            hashed_password=await hash_password("testpass123"),
            role=Role.user,
        )
        await crud.create_user(db, user)
    yield user
    async with database._session_factory() as db:
        await crud.delete_user(db, user.id)


async def test_login_beyond_the_cap_signs_out_the_stalest_session(
    test_client: AsyncClient, fresh_user, clock
):
    from songbirdapi.dependencies import load_settings

    cap = load_settings().session_max_per_user
    devices = []
    for _ in range(cap + 1):
        devices.append(await _login(test_client, fresh_user))
        clock.advance(seconds=1)

    assert (await _refresh(test_client, devices[0]["refresh_token"])).status_code == 401
    for kept in devices[1:]:
        assert (await _refresh(test_client, kept["refresh_token"])).status_code == 200


async def test_disabling_a_user_revokes_their_sessions_for_good(
    test_client: AsyncClient, fresh_user, admin_user
):
    from songbirdapi.routes import admin_user_path

    victim = await _login(test_client, fresh_user)
    admin = await _login(test_client, admin_user)

    test_client.cookies.clear()
    for active in (False, True):
        resp = await test_client.patch(
            admin_user_path(fresh_user.id), json={"is_active": active}, cookies=admin
        )
        assert resp.status_code == 200

    assert (await _refresh(test_client, victim["refresh_token"])).status_code == 401
    assert (await _me(test_client, victim["access_token"])).status_code == 401


async def test_startup_prune_clears_dead_sessions_of_every_user(
    test_client: AsyncClient, fresh_user, regular_user
):
    import uuid

    from sqlalchemy import select

    from songbirdapi import database
    from songbirdapi.dependencies import load_settings
    from songbirdapi.models import AuthSession
    from songbirdapi.routers.auth import prune_dead_sessions

    now = security.utcnow()

    def dead(user):
        return AuthSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            jti="x",
            created_at=now,
            last_used_at=now,
            rotated_at=now,
            revoked_at=now - timedelta(days=8),
        )

    rows = [dead(fresh_user), dead(regular_user)]
    async with database._session_factory() as db:
        db.add_all(rows)
        await db.commit()
        await prune_dead_sessions(db, now, load_settings())
        await db.commit()
        left = (
            await db.execute(
                select(AuthSession.id).where(AuthSession.id.in_([r.id for r in rows]))
            )
        ).all()
    assert left == []


# --- rules the code enforces and nothing else pinned ----------------------------


async def test_access_token_is_not_accepted_as_a_refresh_token_nor_the_reverse(
    test_client: AsyncClient, regular_user
):
    tokens = await _login(test_client, regular_user)

    assert (await _refresh(test_client, tokens["access_token"])).status_code == 401
    assert (await _me(test_client, tokens["refresh_token"])).status_code == 401


async def test_access_token_for_another_users_session_is_rejected(
    test_client: AsyncClient, regular_user, admin_user
):
    from songbirdapi.dependencies import load_settings

    import jwt as pyjwt

    admin_tokens = await _login(test_client, admin_user)
    secret = load_settings().jwt_secret
    sid = pyjwt.decode(admin_tokens["access_token"], secret, algorithms=["HS256"])[
        "sid"
    ]
    forged = security.create_access_token(
        regular_user.id, regular_user.role.value, sid, secret
    )
    assert (await _me(test_client, forged)).status_code == 401


async def test_access_token_stops_working_at_the_90_day_cap(
    test_client: AsyncClient, regular_user, clock
):
    tokens = await _login(test_client, regular_user)
    assert (await _me(test_client, tokens["access_token"])).status_code == 200

    clock.advance(days=91)

    assert (await _me(test_client, tokens["access_token"])).status_code == 401


async def test_disabled_users_tokens_are_rejected(test_client: AsyncClient, fresh_user):
    from songbirdapi import database
    from songbirdapi.models import User

    tokens = await _login(test_client, fresh_user)
    async with database._session_factory() as db:
        user = await db.get(User, fresh_user.id)
        user.is_active = False
        await db.commit()

    assert (await _refresh(test_client, tokens["refresh_token"])).status_code == 401
    assert (await _me(test_client, tokens["access_token"])).status_code == 401


async def test_hold_and_replay_count_as_activity(
    test_client: AsyncClient, fresh_user, clock
):
    tokens = await _login(test_client, fresh_user)
    clock.advance(seconds=61)
    rotated = _set_cookie_attrs(
        await _refresh(test_client, tokens["refresh_token"]), "refresh_token"
    )["value"]
    after_rotate = (await _only_session(fresh_user)).last_used_at

    clock.advance(seconds=10)
    assert (await _refresh(test_client, rotated)).status_code == 200  # hold
    after_hold = (await _only_session(fresh_user)).last_used_at
    assert timedelta(seconds=10) <= after_hold - after_rotate < timedelta(seconds=12)

    clock.advance(seconds=10)
    assert (
        await _refresh(test_client, tokens["refresh_token"])
    ).status_code == 200  # replay of the previous token
    after_replay = (await _only_session(fresh_user)).last_used_at
    assert timedelta(seconds=10) <= after_replay - after_hold < timedelta(seconds=12)


async def _two_generations_old(client: AsyncClient, user, clock) -> dict:
    """Login, rotate twice: the login refresh token is now neither current nor
    previous, so presenting it is reuse."""
    tokens = await _login(client, user)
    clock.advance(seconds=61)
    t1 = _set_cookie_attrs(
        await _refresh(client, tokens["refresh_token"]), "refresh_token"
    )["value"]
    clock.advance(seconds=61)
    await _refresh(client, t1)
    clock.advance(seconds=61)
    return tokens


async def test_reuse_is_logged_as_a_warning(
    test_client: AsyncClient, regular_user, clock, caplog
):
    import logging

    tokens = await _two_generations_old(test_client, regular_user, clock)

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        resp = await _refresh(test_client, tokens["refresh_token"])

    assert resp.status_code == 401
    assert "refresh token reuse: revoked session" in caplog.text


async def test_kill_switch_turns_reuse_into_a_branch(
    test_client: AsyncClient, regular_user, clock, caplog, monkeypatch
):
    import logging

    monkeypatch.setenv("REFRESH_REUSE_DETECTION", "false")
    tokens = await _two_generations_old(test_client, regular_user, clock)

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        resp = await _refresh(test_client, tokens["refresh_token"])

    assert resp.status_code == 200
    assert "detection off: branched session" in caplog.text
    assert (await _me(test_client, tokens["access_token"])).status_code == 200


async def test_login_stores_the_user_agent_cut_to_256_characters(
    test_client: AsyncClient, fresh_user
):
    resp = await test_client.post(
        AUTH_LOGIN,
        json={"username": fresh_user.username, "password": "testpass123"},
        headers={"user-agent": "x" * 300},
    )
    assert resp.status_code == 200

    assert (await _only_session(fresh_user)).user_agent == "x" * 256
