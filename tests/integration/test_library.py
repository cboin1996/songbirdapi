import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        "/v1/auth/login", json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


async def test_library_empty_on_start(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/library", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_add_to_library(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    assert resp.status_code == 201
    body = resp.json()
    assert body["song_id"] == sample_song.uuid
    assert body["last_position"] == 0.0
    assert body["last_played_at"] is None


async def test_add_to_library_idempotent(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    assert resp.status_code == 201


async def test_add_nonexistent_song_returns_404(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post("/v1/library/does-not-exist", cookies=cookies)
    assert resp.status_code == 404


async def test_library_contains_added_song(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.get("/v1/library", cookies=cookies)
    assert resp.status_code == 200
    assert any(e["song_id"] == sample_song.uuid for e in resp.json())


async def test_remove_from_library(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.delete(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    assert resp.status_code == 204
    resp = await test_client.get("/v1/library", cookies=cookies)
    assert not any(e["song_id"] == sample_song.uuid for e in resp.json())


async def test_remove_from_library_cleans_offline(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    await test_client.post(f"/v1/library/offline/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.get("/v1/library/offline", cookies=cookies)
    assert sample_song.uuid in resp.json()

    await test_client.delete(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.get("/v1/library/offline", cookies=cookies)
    assert sample_song.uuid not in resp.json()


async def test_remove_nonexistent_returns_404(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.delete("/v1/library/does-not-exist", cookies=cookies)
    assert resp.status_code == 404


async def test_update_position(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    resp = await test_client.patch(
        f"/v1/library/{sample_song.uuid}/position",
        json={"position": 42.5},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_position"] == 42.5
    assert body["last_played_at"] is not None


@pytest.mark.xfail(
    reason="source bug: PATCH /library/{id}/position returns 204 instead of 404 when entry missing (routers/library.py:160)",
    strict=True,
)
async def test_update_position_not_in_library_returns_404(
    test_client: AsyncClient, regular_user
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.patch(
        "/v1/library/00000000-0000-0000-0000-000000000000/position",
        json={"position": 10.0},
        cookies=cookies,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


async def test_get_library_requires_auth(test_client: AsyncClient):
    resp = await test_client.get("/v1/library")
    assert resp.status_code == 401


async def test_add_to_library_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.post(f"/v1/library/{sample_song.uuid}")
    assert resp.status_code == 401


async def test_remove_from_library_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.delete(f"/v1/library/{sample_song.uuid}")
    assert resp.status_code == 401


async def test_update_position_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.patch(
        f"/v1/library/{sample_song.uuid}/position", json={"position": 0.0}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /publish
# ---------------------------------------------------------------------------


async def test_publish_requires_auth(test_client: AsyncClient):
    resp = await test_client.post("/v1/library/publish")
    assert resp.status_code == 401


async def test_publish_returns_count(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        "/v1/library/publish", json={"song_ids": []}, cookies=cookies
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "published" in body
    assert isinstance(body["published"], int)


# ---------------------------------------------------------------------------
# DELETE /library/bulk
# ---------------------------------------------------------------------------


async def test_bulk_remove_from_library(
    test_client: AsyncClient, regular_user, sample_song
):
    import uuid as _uuid

    cookies = await login(test_client, regular_user)
    # create a second song in-band via the song fixture pattern isn't available, so insert via library add
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession

    second_uuid = str(_uuid.uuid4())
    async with _TestingSession() as db:
        song2 = _Song(
            uuid=second_uuid,
            url="https://example.com/bulk-song2",
            file_path="/tmp/bulk-song2.mp3",
        )
        await _crud.insert_song(db, song2)
    # add both to library
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    await test_client.post(f"/v1/library/{second_uuid}", cookies=cookies)
    # bulk remove both
    resp = await test_client.request(
        "DELETE",
        "/v1/library/bulk",
        json={"song_ids": [sample_song.uuid, second_uuid]},
        cookies=cookies,
    )
    assert resp.status_code == 204
    lib = await test_client.get("/v1/library", cookies=cookies)
    uuids = [e["song_id"] for e in lib.json()]
    assert sample_song.uuid not in uuids
    assert second_uuid not in uuids
    # cleanup
    async with _TestingSession() as db:
        await _crud.delete_song(db, second_uuid)


async def test_bulk_remove_cleans_offline(
    test_client: AsyncClient, regular_user, sample_song
):
    import uuid as _uuid

    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession

    cookies = await login(test_client, regular_user)
    second_uuid = str(_uuid.uuid4())
    async with _TestingSession() as db:
        song2 = _Song(
            uuid=second_uuid,
            url="https://example.com/bulk-offline-song2",
            file_path="/tmp/bulk-offline-song2.mp3",
        )
        await _crud.insert_song(db, song2)
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    await test_client.post(f"/v1/library/{second_uuid}", cookies=cookies)
    await test_client.post(f"/v1/library/offline/{sample_song.uuid}", cookies=cookies)
    await test_client.post(f"/v1/library/offline/{second_uuid}", cookies=cookies)

    resp = await test_client.request(
        "DELETE",
        "/v1/library/bulk",
        json={"song_ids": [sample_song.uuid, second_uuid]},
        cookies=cookies,
    )
    assert resp.status_code == 204
    resp = await test_client.get("/v1/library/offline", cookies=cookies)
    offline_ids = resp.json()
    assert sample_song.uuid not in offline_ids
    assert second_uuid not in offline_ids

    async with _TestingSession() as db:
        await _crud.delete_song(db, second_uuid)


async def test_bulk_remove_partial(test_client: AsyncClient, regular_user, sample_song):
    import uuid as _uuid

    cookies = await login(test_client, regular_user)
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession

    third_uuid = str(_uuid.uuid4())
    async with _TestingSession() as db:
        song3 = _Song(
            uuid=third_uuid,
            url="https://example.com/bulk-song3",
            file_path="/tmp/bulk-song3.mp3",
        )
        await _crud.insert_song(db, song3)
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    await test_client.post(f"/v1/library/{third_uuid}", cookies=cookies)
    # bulk remove only third
    resp = await test_client.request(
        "DELETE",
        "/v1/library/bulk",
        json={"song_ids": [third_uuid]},
        cookies=cookies,
    )
    assert resp.status_code == 204
    lib = await test_client.get("/v1/library", cookies=cookies)
    uuids = [e["song_id"] for e in lib.json()]
    assert third_uuid not in uuids
    assert sample_song.uuid in uuids
    # cleanup
    await test_client.request(
        "DELETE",
        "/v1/library/bulk",
        json={"song_ids": [sample_song.uuid]},
        cookies=cookies,
    )
    async with _TestingSession() as db:
        await _crud.delete_song(db, third_uuid)


async def test_bulk_remove_empty_list_returns_400(
    test_client: AsyncClient, regular_user
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.request(
        "DELETE", "/v1/library/bulk", json={"song_ids": []}, cookies=cookies
    )
    assert resp.status_code == 400


async def test_bulk_remove_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.request(
        "DELETE", "/v1/library/bulk", json={"song_ids": [sample_song.uuid]}
    )
    assert resp.status_code == 401
