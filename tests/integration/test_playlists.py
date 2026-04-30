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


async def test_list_playlists_requires_auth(test_client: AsyncClient):
    resp = await test_client.get("/v1/playlists")
    assert resp.status_code == 401


async def test_create_playlist_requires_auth(test_client: AsyncClient):
    resp = await test_client.post("/v1/playlists", json={"name": "unauth"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_list_playlists_empty(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/playlists", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_playlist(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        "/v1/playlists", json={"name": "my playlist"}, cookies=cookies
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "my playlist"
    assert "id" in body
    assert body["song_count"] == 0
    # cleanup
    await test_client.delete(f"/v1/playlists/{body['id']}", cookies=cookies)


async def test_create_playlist_appears_in_list(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "listme"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    resp = await test_client.get("/v1/playlists", cookies=cookies)
    assert resp.status_code == 200
    assert any(p["id"] == pl_id for p in resp.json())
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_rename_playlist(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "old name"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    resp = await test_client.patch(
        f"/v1/playlists/{pl_id}", json={"name": "new name"}, cookies=cookies
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "new name"
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_delete_playlist(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "to delete"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    resp = await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)
    assert resp.status_code == 204
    listing = await test_client.get("/v1/playlists", cookies=cookies)
    assert not any(p["id"] == pl_id for p in listing.json())


async def test_delete_nonexistent_playlist(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.delete(
        "/v1/playlists/fake-id-does-not-exist", cookies=cookies
    )
    assert resp.status_code == 404


async def test_cannot_access_other_users_playlist(
    test_client: AsyncClient, regular_user, admin_user
):
    reg_cookies = await login(test_client, regular_user)
    adm_cookies = await login(test_client, admin_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "private"}, cookies=reg_cookies
    )
    pl_id = create.json()["id"]
    resp = await test_client.patch(
        f"/v1/playlists/{pl_id}", json={"name": "hacked"}, cookies=adm_cookies
    )
    assert resp.status_code == 404
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=reg_cookies)


# ---------------------------------------------------------------------------
# Song management
# ---------------------------------------------------------------------------


async def test_add_song_to_playlist(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "with song"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    resp = await test_client.post(
        f"/v1/playlists/{pl_id}/songs",
        json={"song_uuid": sample_song.uuid},
        cookies=cookies,
    )
    assert resp.status_code == 204
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_get_playlist_songs(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "songs list"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    await test_client.post(
        f"/v1/playlists/{pl_id}/songs",
        json={"song_uuid": sample_song.uuid},
        cookies=cookies,
    )
    resp = await test_client.get(f"/v1/playlists/{pl_id}/songs", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(s["uuid"] == sample_song.uuid for s in body)
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_add_duplicate_song(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "dupe test"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    await test_client.post(
        f"/v1/playlists/{pl_id}/songs",
        json={"song_uuid": sample_song.uuid},
        cookies=cookies,
    )
    resp = await test_client.post(
        f"/v1/playlists/{pl_id}/songs",
        json={"song_uuid": sample_song.uuid},
        cookies=cookies,
    )
    assert resp.status_code == 409
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_add_nonexistent_song(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "bad song"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    resp = await test_client.post(
        f"/v1/playlists/{pl_id}/songs",
        json={"song_uuid": "00000000-0000-0000-0000-000000000000"},
        cookies=cookies,
    )
    assert resp.status_code == 404
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_remove_song_from_playlist(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "remove song"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    await test_client.post(
        f"/v1/playlists/{pl_id}/songs",
        json={"song_uuid": sample_song.uuid},
        cookies=cookies,
    )
    resp = await test_client.delete(
        f"/v1/playlists/{pl_id}/songs/{sample_song.uuid}", cookies=cookies
    )
    assert resp.status_code == 204
    songs = await test_client.get(f"/v1/playlists/{pl_id}/songs", cookies=cookies)
    assert songs.json() == []
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_reorder_playlist(test_client: AsyncClient, regular_user, sample_song):
    import uuid as _uuid

    cookies = await login(test_client, regular_user)
    # create a second song via the songs endpoint isn't available here, so we
    # reorder with a single-element list to verify the endpoint is wired correctly
    create = await test_client.post(
        "/v1/playlists", json={"name": "reorder"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    await test_client.post(
        f"/v1/playlists/{pl_id}/songs",
        json={"song_uuid": sample_song.uuid},
        cookies=cookies,
    )
    resp = await test_client.patch(
        f"/v1/playlists/{pl_id}/songs",
        json={"song_uuids": [sample_song.uuid]},
        cookies=cookies,
    )
    assert resp.status_code == 204
    songs = await test_client.get(f"/v1/playlists/{pl_id}/songs", cookies=cookies)
    assert songs.json()[0]["uuid"] == sample_song.uuid
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


# ---------------------------------------------------------------------------
# POST /playlists/{playlist_id}/songs/bulk
# ---------------------------------------------------------------------------


async def test_bulk_add_songs_to_playlist(
    test_client: AsyncClient, regular_user, sample_song
):
    import uuid as _uuid

    cookies = await login(test_client, regular_user)
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession

    second_uuid = str(_uuid.uuid4())
    async with _TestingSession() as db:
        song2 = _Song(
            uuid=second_uuid,
            url="https://example.com/bulk-pl-song2",
            file_path="/tmp/bulk-pl-song2.mp3",
        )
        await _crud.insert_song(db, song2)
    create = await test_client.post(
        "/v1/playlists", json={"name": "bulk add"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    # add both songs to library first
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    await test_client.post(f"/v1/library/{second_uuid}", cookies=cookies)
    resp = await test_client.post(
        f"/v1/playlists/{pl_id}/songs/bulk",
        json={"song_uuids": [sample_song.uuid, second_uuid]},
        cookies=cookies,
    )
    assert resp.status_code == 204
    songs = await test_client.get(f"/v1/playlists/{pl_id}/songs", cookies=cookies)
    uuids = [s["uuid"] for s in songs.json()]
    assert sample_song.uuid in uuids
    assert second_uuid in uuids
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)
    async with _TestingSession() as db:
        await _crud.delete_song(db, second_uuid)


async def test_bulk_add_skips_duplicates(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await test_client.post(f"/v1/library/{sample_song.uuid}", cookies=cookies)
    create = await test_client.post(
        "/v1/playlists", json={"name": "bulk dedup"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    # add same song twice in one bulk call
    resp = await test_client.post(
        f"/v1/playlists/{pl_id}/songs/bulk",
        json={"song_uuids": [sample_song.uuid, sample_song.uuid]},
        cookies=cookies,
    )
    assert resp.status_code == 204
    songs = await test_client.get(f"/v1/playlists/{pl_id}/songs", cookies=cookies)
    uuids = [s["uuid"] for s in songs.json()]
    assert uuids.count(sample_song.uuid) == 1
    # add same song again via a second bulk call — should still be once
    resp2 = await test_client.post(
        f"/v1/playlists/{pl_id}/songs/bulk",
        json={"song_uuids": [sample_song.uuid]},
        cookies=cookies,
    )
    assert resp2.status_code == 204
    songs2 = await test_client.get(f"/v1/playlists/{pl_id}/songs", cookies=cookies)
    assert [s["uuid"] for s in songs2.json()].count(sample_song.uuid) == 1
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_bulk_add_empty_list_returns_400(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "bulk empty"}, cookies=cookies
    )
    pl_id = create.json()["id"]
    resp = await test_client.post(
        f"/v1/playlists/{pl_id}/songs/bulk",
        json={"song_uuids": []},
        cookies=cookies,
    )
    assert resp.status_code == 400
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_bulk_add_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.post(
        "/v1/playlists/fake-playlist-id/songs/bulk",
        json={"song_uuids": [sample_song.uuid]},
    )
    assert resp.status_code == 401


async def test_bulk_add_wrong_user_returns_403(
    test_client: AsyncClient, regular_user, admin_user, sample_song
):
    reg_cookies = await login(test_client, regular_user)
    adm_cookies = await login(test_client, admin_user)
    create = await test_client.post(
        "/v1/playlists", json={"name": "owner only"}, cookies=reg_cookies
    )
    pl_id = create.json()["id"]
    resp = await test_client.post(
        f"/v1/playlists/{pl_id}/songs/bulk",
        json={"song_uuids": [sample_song.uuid]},
        cookies=adm_cookies,
    )
    assert resp.status_code == 403
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=reg_cookies)
