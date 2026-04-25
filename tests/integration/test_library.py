import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post("/auth/login", json={"username": user.username, "password": "testpass123"})
    return dict(resp.cookies)


async def test_library_empty_on_start(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/library", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_add_to_library(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(f"/library/{sample_song.uuid}", cookies=cookies)
    assert resp.status_code == 201
    body = resp.json()
    assert body["song_id"] == sample_song.uuid
    assert body["last_position"] == 0.0
    assert body["last_played_at"] is None


async def test_add_to_library_idempotent(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/library/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.post(f"/library/{sample_song.uuid}", cookies=cookies)
    assert resp.status_code == 201


async def test_add_nonexistent_song_returns_404(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post("/library/does-not-exist", cookies=cookies)
    assert resp.status_code == 404


async def test_library_contains_added_song(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/library/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.get("/library", cookies=cookies)
    assert resp.status_code == 200
    assert any(e["song_id"] == sample_song.uuid for e in resp.json())


async def test_remove_from_library(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/library/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.delete(f"/library/{sample_song.uuid}", cookies=cookies)
    assert resp.status_code == 204
    resp = await test_client.get("/library", cookies=cookies)
    assert not any(e["song_id"] == sample_song.uuid for e in resp.json())


async def test_remove_nonexistent_returns_404(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.delete("/library/does-not-exist", cookies=cookies)
    assert resp.status_code == 404


async def test_update_position(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/library/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.patch(f"/library/{sample_song.uuid}/position", json={"position": 42.5}, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_position"] == 42.5
    assert body["last_played_at"] is not None


async def test_update_position_not_in_library_returns_404(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.patch("/library/00000000-0000-0000-0000-000000000000/position", json={"position": 10.0}, cookies=cookies)
    assert resp.status_code == 404
