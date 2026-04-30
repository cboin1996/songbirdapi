"""
Pool/connection-handling regression tests.

Background: under e2e load we hit pool exhaustion + the asyncpg
"cannot switch to state 15" race. The fix combined:
  - bcrypt offload to asyncio.to_thread (was blocking the loop)
  - pool_pre_ping=False (was racing pg_idle_in_transaction_session_timeout)
  - pool_recycle=600s + pg-side idle_in_tx timeout=120s as a self-heal net
  - session_scope rolls back in finally so read-only / autobegan tx release
  - streaming/IO endpoints (downloads, artwork, share download, edit job,
    properties tagger, imports upload) release the session before the
    blocking IO so the connection isn't pinned for the duration

These tests lock in those guarantees by introspecting engine.pool directly.
The conftest.py engine is shared with the app via database._engine override,
so engine.pool.checkedout() reflects what the routes see.
"""

import asyncio

import pytest
from httpx import AsyncClient

from songbirdapi import database

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _checkedout() -> int:
    return database._engine.pool.checkedout()


async def _login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        "/v1/auth/login", json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


async def test_read_endpoint_releases_connection_after_response(
    test_client: AsyncClient, regular_user
):
    """A read endpoint must return its connection to the pool when the
    response completes. Loops 50× to expose any per-request leak."""
    cookies = await _login(test_client, regular_user)
    baseline = _checkedout()
    for _ in range(50):
        resp = await test_client.get("/v1/library", cookies=cookies)
        assert resp.status_code == 200
    # Allow one in-flight settle — the test client's own request is in
    # flight when this line runs the next time, but with no in-flight
    # request the count must equal baseline.
    await asyncio.sleep(0.05)
    assert (
        _checkedout() == baseline
    ), f"connection leaked: baseline={baseline}, after 50 reads={_checkedout()}"


async def test_write_endpoint_releases_connection_after_response(
    test_client: AsyncClient, regular_user, sample_song
):
    """Write paths commit then return — the commit clears the autobegan
    tx, and session close releases the connection. Verify by looping."""
    cookies = await _login(test_client, regular_user)
    baseline = _checkedout()
    for _ in range(20):
        # Add then remove — idempotent loop, doesn't leak rows.
        r1 = await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
        assert r1.status_code == 201
        r2 = await test_client.delete(
            f"/v1/library/{sample_song.uuid}", cookies=cookies
        )
        assert r2.status_code == 204
    await asyncio.sleep(0.05)
    assert _checkedout() == baseline


async def test_endpoint_raising_404_releases_connection(
    test_client: AsyncClient, regular_user
):
    """When an endpoint raises HTTPException mid-handler, FastAPI still
    runs the get_db dependency cleanup. session_scope's finally rollback
    must fire so the connection returns to the pool."""
    cookies = await _login(test_client, regular_user)
    baseline = _checkedout()
    for _ in range(50):
        resp = await test_client.get("/v1/songs/does-not-exist-xyz", cookies=cookies)
        assert resp.status_code == 404
    await asyncio.sleep(0.05)
    assert _checkedout() == baseline


async def test_concurrent_burst_does_not_exhaust_pool(
    test_client: AsyncClient, regular_user
):
    """50 concurrent /v1/library reads against pool_size=20 + max_overflow=10
    must all complete (overflow + queueing handles the surge). If any
    request blocks indefinitely or 500s, the pool is mishandled."""
    cookies = await _login(test_client, regular_user)
    baseline = _checkedout()

    async def one():
        r = await test_client.get("/v1/library", cookies=cookies)
        assert r.status_code == 200

    await asyncio.gather(*(one() for _ in range(50)))
    await asyncio.sleep(0.1)
    assert _checkedout() == baseline


async def test_streaming_artwork_releases_session_before_stream(
    test_client: AsyncClient, regular_user, sample_song
):
    """Streaming endpoints (artwork, downloads, share) wrap the DB read in
    session_scope so the connection is released BEFORE the FileResponse
    is returned. Verifies the migration we did to fix /library 50-fanout
    pool exhaustion. We use a 404 path here because sample_song has no
    artwork file — we just need the route to do its DB lookup and return
    without holding a connection."""
    cookies = await _login(test_client, regular_user)
    baseline = _checkedout()
    # 404 is fine — handler still goes through session_scope read path
    for _ in range(30):
        resp = await test_client.get(
            f"/v1/songs/{sample_song.uuid}/artwork/full", cookies=cookies
        )
        assert resp.status_code == 404
    await asyncio.sleep(0.05)
    assert _checkedout() == baseline


async def test_pool_size_within_configured_limits(test_client: AsyncClient):
    """Smoke test: under no load, pool should never exceed configured size.
    pool.size() reports persistent connections (capped at pool_size=20).
    Catches drift if someone changes init_engine without updating the
    integration tests' baseline."""
    # No requests in flight here — pool should be near zero checkedout.
    assert _checkedout() <= database._engine.pool.size()


async def test_health_endpoint_releases_db_session(test_client: AsyncClient):
    """The /v1/health endpoint runs SELECT 1 via Depends(get_db). If that
    leaks a connection per call, an external monitor probing /health every
    few seconds drains the pool over hours. Verify by hammering it."""
    baseline = _checkedout()
    for _ in range(100):
        resp = await test_client.get("/v1/health")
        assert resp.status_code == 200
    await asyncio.sleep(0.05)
    assert _checkedout() == baseline
