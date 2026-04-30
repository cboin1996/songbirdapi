import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        "/v1/auth/login", json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def test_download_post_requires_auth(test_client: AsyncClient):
    resp = await test_client.post(
        "/v1/download", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    )
    assert resp.status_code == 401


async def test_get_download_requires_auth(test_client: AsyncClient):
    resp = await test_client.get("/v1/download/nonexistent-id")
    assert resp.status_code == 401


async def test_delete_download_requires_auth(test_client: AsyncClient):
    resp = await test_client.delete("/v1/download/nonexistent-id")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /download/{id} — 404 for missing song
# ---------------------------------------------------------------------------


async def test_get_download_not_found(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(
        "/v1/download/00000000-0000-0000-0000-000000000000", cookies=cookies
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /download/{id} — succeeds even when song doesn't exist (no-op)
# ---------------------------------------------------------------------------


async def test_delete_download_nonexistent_is_ok(
    test_client: AsyncClient, regular_user
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.delete(
        "/v1/download/00000000-0000-0000-0000-000000000000", cookies=cookies
    )
    # router does not raise on missing — just deletes nothing
    assert resp.status_code in (200, 204)


# ---------------------------------------------------------------------------
# POST /download/ — cached-song path (url already in DB)
# ---------------------------------------------------------------------------


async def test_download_cached_returns_existing_song(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        "/v1/download",
        json={"url": sample_song.url, "ignore_cache": False},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "song_ids" in body
    assert sample_song.uuid in body["song_ids"]
