import pytest
from httpx import AsyncClient
from songbirdapi.routes import AUTH_LOGIN, PLAYER_STATE, PLAYER_QUEUE, PLAYER_QUEUE_REORDER, player_queue_song_path

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


async def test_get_player_state(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(PLAYER_STATE, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "shuffle" in body
    assert "repeat" in body
    assert "queue" in body
    assert "queue_index" in body


async def test_put_player_state(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        PLAYER_STATE,
        json={"shuffle": True, "repeat": "all", "queue": [], "queue_index": -1},
        cookies=cookies,
    )
    assert resp.status_code in (200, 204)


async def test_player_state_persists(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    await test_client.put(
        PLAYER_STATE,
        json={"shuffle": True, "repeat": "all", "queue": [], "queue_index": -1},
        cookies=cookies,
    )
    resp = await test_client.get(PLAYER_STATE, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["shuffle"] is True
    assert body["repeat"] == "all"


async def test_get_player_state_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(PLAYER_STATE)
    assert resp.status_code == 401


async def test_put_player_state_requires_auth(test_client: AsyncClient):
    resp = await test_client.put(
        PLAYER_STATE,
        json={"shuffle": False, "repeat": "off", "queue": [], "queue_index": -1},
    )
    assert resp.status_code == 401


async def test_put_player_state_invalid_repeat(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        PLAYER_STATE,
        json={
            "shuffle": False,
            "repeat": "invalid_value",
            "queue": [],
            "queue_index": -1,
        },
        cookies=cookies,
    )
    assert resp.status_code == 422


async def test_put_player_state_with_queue(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        PLAYER_STATE,
        json={
            "shuffle": False,
            "repeat": "one",
            "queue": [sample_song.uuid],
            "queue_index": 0,
        },
        cookies=cookies,
    )
    assert resp.status_code in (200, 204)
    if resp.status_code == 200:
        body = resp.json()
        assert body["queue"] == [sample_song.uuid]
        assert body["queue_index"] == 0


async def test_put_player_state_with_queue_sources(
    test_client: AsyncClient, regular_user, sample_song
):
    """PUT with queue_sources populated, GET returns the same dict."""
    cookies = await login(test_client, regular_user)
    queue_sources = {
        sample_song.uuid: {
            "id": "library",
            "label": "Library",
            "href": f"/library?song={sample_song.uuid}",
        }
    }
    resp = await test_client.put(
        PLAYER_STATE,
        json={
            "shuffle": False,
            "repeat": "off",
            "queue": [sample_song.uuid],
            "queue_index": 0,
            "queue_sources": queue_sources,
        },
        cookies=cookies,
    )
    assert resp.status_code in (200, 204)

    # GET and verify queue_sources
    resp = await test_client.get(PLAYER_STATE, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue_sources"] == queue_sources


async def test_put_player_state_without_queue_sources_legacy(
    test_client: AsyncClient, regular_user
):
    """PUT without queue_sources (legacy clients) should not error, default to {}."""
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        PLAYER_STATE,
        json={"shuffle": False, "repeat": "off", "queue": [], "queue_index": -1},
        cookies=cookies,
    )
    assert resp.status_code in (200, 204)

    # GET and verify queue_sources defaults to {}
    resp = await test_client.get(PLAYER_STATE, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue_sources"] == {}


async def test_queue_sources_roundtrip_with_uuid(
    test_client: AsyncClient, regular_user, sample_song
):
    """Roundtrip an entry with UUID key and all required fields."""
    cookies = await login(test_client, regular_user)
    source_uuid = sample_song.uuid
    queue_sources = {
        source_uuid: {
            "id": "library",
            "label": "Library",
            "href": f"/library?song={source_uuid}",
        }
    }

    # PUT
    resp = await test_client.put(
        PLAYER_STATE,
        json={
            "shuffle": False,
            "repeat": "all",
            "queue": [source_uuid],
            "queue_index": 0,
            "queue_sources": queue_sources,
        },
        cookies=cookies,
    )
    assert resp.status_code in (200, 204)

    # First GET
    resp = await test_client.get(PLAYER_STATE, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert source_uuid in body["queue_sources"]
    assert body["queue_sources"][source_uuid] == queue_sources[source_uuid]

    # Second GET to verify persistence
    resp = await test_client.get(PLAYER_STATE, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue_sources"] == queue_sources


async def test_put_player_state_malformed_queue_source(
    test_client: AsyncClient, regular_user, sample_song
):
    """PUT with malformed source (missing required field) should return 422."""
    cookies = await login(test_client, regular_user)
    queue_sources = {
        sample_song.uuid: {
            "id": "library",
            # Missing required 'label' field
            "href": f"/library?song={sample_song.uuid}",
        }
    }
    resp = await test_client.put(
        PLAYER_STATE,
        json={
            "shuffle": False,
            "repeat": "off",
            "queue": [sample_song.uuid],
            "queue_index": 0,
            "queue_sources": queue_sources,
        },
        cookies=cookies,
    )
    assert resp.status_code == 422


async def test_player_state_returns_updated_at(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    await test_client.put(
        PLAYER_STATE,
        json={"shuffle": False, "repeat": "off", "queue": [], "queue_index": -1},
        cookies=cookies,
    )
    resp = await test_client.get(PLAYER_STATE, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "updated_at" in body
    assert body["updated_at"] is not None


# --- Queue mutation endpoints ---


async def _seed_queue(test_client, cookies, queue, shuffle=False, shuffle_order=None):
    await test_client.put(
        PLAYER_STATE,
        json={
            "shuffle": shuffle,
            "repeat": "off",
            "queue": queue,
            "queue_index": 0,
            "shuffle_order": shuffle_order,
            "shuffle_seed": 42 if shuffle else None,
            "shuffle_position": 0,
        },
        cookies=cookies,
    )


async def test_queue_insert_appends_to_end(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(test_client, cookies, [sample_song.uuid])

    resp = await test_client.post(
        PLAYER_QUEUE,
        json={"song_id": second_song.uuid},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == [sample_song.uuid, second_song.uuid]


async def test_queue_insert_at_position(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(test_client, cookies, [sample_song.uuid])

    resp = await test_client.post(
        PLAYER_QUEUE,
        json={"song_id": second_song.uuid, "position": 0},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == [second_song.uuid, sample_song.uuid]
    assert body["queue_index"] == 1


async def test_queue_insert_duplicate_is_noop(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(test_client, cookies, [sample_song.uuid])

    resp = await test_client.post(
        PLAYER_QUEUE,
        json={"song_id": sample_song.uuid},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == [sample_song.uuid]


async def test_queue_insert_with_source(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(test_client, cookies, [sample_song.uuid])

    source = {"id": "library", "label": "Library", "href": "/library"}
    resp = await test_client.post(
        PLAYER_QUEUE,
        json={"song_id": second_song.uuid, "source": source},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue_sources"][second_song.uuid] == source


async def test_queue_insert_updates_shuffle_order(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(
        test_client, cookies, [sample_song.uuid],
        shuffle=True, shuffle_order=[0],
    )

    resp = await test_client.post(
        PLAYER_QUEUE,
        json={"song_id": second_song.uuid},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["shuffle_order"]) == 2
    assert set(body["shuffle_order"]) == {0, 1}


async def test_queue_insert_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.post(
        PLAYER_QUEUE,
        json={"song_id": sample_song.uuid},
    )
    assert resp.status_code == 401


async def test_queue_remove_song(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(test_client, cookies, [sample_song.uuid, second_song.uuid])

    resp = await test_client.delete(
        player_queue_song_path(second_song.uuid),
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == [sample_song.uuid]


async def test_queue_remove_adjusts_index(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    await test_client.put(
        PLAYER_STATE,
        json={
            "shuffle": False, "repeat": "off",
            "queue": [sample_song.uuid, second_song.uuid],
            "queue_index": 1,
        },
        cookies=cookies,
    )

    resp = await test_client.delete(
        player_queue_song_path(sample_song.uuid),
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == [second_song.uuid]
    assert body["queue_index"] == 0


async def test_queue_remove_missing_song_is_noop(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(test_client, cookies, [sample_song.uuid])

    resp = await test_client.delete(
        player_queue_song_path("nonexistent-uuid"),
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == [sample_song.uuid]


async def test_queue_remove_cleans_manual_next_and_sources(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    source = {"id": "library", "label": "Library", "href": "/library"}
    await test_client.put(
        PLAYER_STATE,
        json={
            "shuffle": False, "repeat": "off",
            "queue": [sample_song.uuid, second_song.uuid],
            "queue_index": 0,
            "manual_next": [second_song.uuid],
            "queue_sources": {second_song.uuid: source},
        },
        cookies=cookies,
    )

    resp = await test_client.delete(
        player_queue_song_path(second_song.uuid),
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert second_song.uuid not in body["manual_next"]
    assert second_song.uuid not in body["queue_sources"]


async def test_queue_remove_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.delete(
        player_queue_song_path(sample_song.uuid),
    )
    assert resp.status_code == 401


async def test_queue_reorder_shuffle_off(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(test_client, cookies, [sample_song.uuid, second_song.uuid])

    resp = await test_client.put(
        PLAYER_QUEUE_REORDER,
        json={"from_position": 1, "to_position": 0},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == [second_song.uuid, sample_song.uuid]


async def test_queue_reorder_updates_current_index(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(test_client, cookies, [sample_song.uuid, second_song.uuid])

    resp = await test_client.put(
        PLAYER_QUEUE_REORDER,
        json={"from_position": 0, "to_position": 2},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == [second_song.uuid, sample_song.uuid]
    assert body["queue_index"] == 1


async def test_queue_reorder_shuffle_on(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(
        test_client, cookies, [sample_song.uuid, second_song.uuid],
        shuffle=True, shuffle_order=[0, 1],
    )

    resp = await test_client.put(
        PLAYER_QUEUE_REORDER,
        json={"from_position": 1, "to_position": 0},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["shuffle_order"] == [1, 0]
    assert body["queue"] == [sample_song.uuid, second_song.uuid]


async def test_queue_reorder_noop_same_position(
    test_client: AsyncClient, regular_user, sample_song, second_song
):
    cookies = await login(test_client, regular_user)
    await _seed_queue(test_client, cookies, [sample_song.uuid, second_song.uuid])

    resp = await test_client.put(
        PLAYER_QUEUE_REORDER,
        json={"from_position": 0, "to_position": 0},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["queue"] == [sample_song.uuid, second_song.uuid]


async def test_queue_reorder_requires_auth(test_client: AsyncClient):
    resp = await test_client.put(
        PLAYER_QUEUE_REORDER,
        json={"from_position": 0, "to_position": 1},
    )
    assert resp.status_code == 401
