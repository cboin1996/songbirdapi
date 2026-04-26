import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post("/v1/auth/login", json={"username": user.username, "password": "testpass123"})
    return dict(resp.cookies)


async def test_list_songs_requires_auth(test_client: AsyncClient):
    resp = await test_client.get("/v1/songs/")
    assert resp.status_code == 401


async def test_list_songs(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/songs/", cookies=cookies)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_library_songs_contains_uuid(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.get("/v1/songs/library", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(e["uuid"] == sample_song.uuid for e in body)


async def test_record_play(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(f"/v1/songs/{sample_song.uuid}/play", cookies=cookies)
    assert resp.status_code in (200, 204)


async def test_explore_week(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/songs/explore?window=week", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "most_played" in body
    assert "recently_added" in body


async def test_explore_day(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/songs/explore?window=day", cookies=cookies)
    assert resp.status_code == 200


async def test_explore_all(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/songs/explore?window=all", cookies=cookies)
    assert resp.status_code == 200
