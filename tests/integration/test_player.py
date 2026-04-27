import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post("/v1/auth/login", json={"username": user.username, "password": "testpass123"})
    return dict(resp.cookies)


async def test_get_player_state(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/player/state", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "shuffle" in body
    assert "repeat" in body
    assert "queue" in body
    assert "queue_index" in body


async def test_put_player_state(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        "/v1/player/state",
        json={"shuffle": True, "repeat": "all", "queue": [], "queue_index": -1},
        cookies=cookies,
    )
    assert resp.status_code in (200, 204)


async def test_player_state_persists(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    await test_client.put(
        "/v1/player/state",
        json={"shuffle": True, "repeat": "all", "queue": [], "queue_index": -1},
        cookies=cookies,
    )
    resp = await test_client.get("/v1/player/state", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["shuffle"] is True
    assert body["repeat"] == "all"


async def test_get_player_state_requires_auth(test_client: AsyncClient):
    resp = await test_client.get("/v1/player/state")
    assert resp.status_code == 401


async def test_put_player_state_requires_auth(test_client: AsyncClient):
    resp = await test_client.put(
        "/v1/player/state",
        json={"shuffle": False, "repeat": "off", "queue": [], "queue_index": -1},
    )
    assert resp.status_code == 401


async def test_put_player_state_invalid_repeat(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        "/v1/player/state",
        json={"shuffle": False, "repeat": "invalid_value", "queue": [], "queue_index": -1},
        cookies=cookies,
    )
    assert resp.status_code == 422


async def test_put_player_state_with_queue(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        "/v1/player/state",
        json={"shuffle": False, "repeat": "one", "queue": [sample_song.uuid], "queue_index": 0},
        cookies=cookies,
    )
    assert resp.status_code in (200, 204)
    if resp.status_code == 200:
        body = resp.json()
        assert body["queue"] == [sample_song.uuid]
        assert body["queue_index"] == 0
