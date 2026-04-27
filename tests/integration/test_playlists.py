import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post("/v1/auth/login", json={"username": user.username, "password": "testpass123"})
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
    resp = await test_client.post("/v1/playlists", json={"name": "my playlist"}, cookies=cookies)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "my playlist"
    assert "id" in body
    assert body["song_count"] == 0
    # cleanup
    await test_client.delete(f"/v1/playlists/{body['id']}", cookies=cookies)


async def test_create_playlist_appears_in_list(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    create = await test_client.post("/v1/playlists", json={"name": "listme"}, cookies=cookies)
    pl_id = create.json()["id"]
    resp = await test_client.get("/v1/playlists", cookies=cookies)
    assert resp.status_code == 200
    assert any(p["id"] == pl_id for p in resp.json())
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_rename_playlist(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    create = await test_client.post("/v1/playlists", json={"name": "old name"}, cookies=cookies)
    pl_id = create.json()["id"]
    resp = await test_client.patch(f"/v1/playlists/{pl_id}", json={"name": "new name"}, cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["name"] == "new name"
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_delete_playlist(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    create = await test_client.post("/v1/playlists", json={"name": "to delete"}, cookies=cookies)
    pl_id = create.json()["id"]
    resp = await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)
    assert resp.status_code == 204
    listing = await test_client.get("/v1/playlists", cookies=cookies)
    assert not any(p["id"] == pl_id for p in listing.json())


async def test_delete_nonexistent_playlist(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.delete("/v1/playlists/fake-id-does-not-exist", cookies=cookies)
    assert resp.status_code == 404


async def test_cannot_access_other_users_playlist(test_client: AsyncClient, regular_user, admin_user):
    reg_cookies = await login(test_client, regular_user)
    adm_cookies = await login(test_client, admin_user)
    create = await test_client.post("/v1/playlists", json={"name": "private"}, cookies=reg_cookies)
    pl_id = create.json()["id"]
    resp = await test_client.patch(f"/v1/playlists/{pl_id}", json={"name": "hacked"}, cookies=adm_cookies)
    assert resp.status_code == 404
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=reg_cookies)


# ---------------------------------------------------------------------------
# Song management
# ---------------------------------------------------------------------------

async def test_add_song_to_playlist(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    create = await test_client.post("/v1/playlists", json={"name": "with song"}, cookies=cookies)
    pl_id = create.json()["id"]
    resp = await test_client.post(f"/v1/playlists/{pl_id}/songs", json={"song_uuid": sample_song.uuid}, cookies=cookies)
    assert resp.status_code == 204
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_get_playlist_songs(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    create = await test_client.post("/v1/playlists", json={"name": "songs list"}, cookies=cookies)
    pl_id = create.json()["id"]
    await test_client.post(f"/v1/playlists/{pl_id}/songs", json={"song_uuid": sample_song.uuid}, cookies=cookies)
    resp = await test_client.get(f"/v1/playlists/{pl_id}/songs", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(s["uuid"] == sample_song.uuid for s in body)
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_add_duplicate_song(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    create = await test_client.post("/v1/playlists", json={"name": "dupe test"}, cookies=cookies)
    pl_id = create.json()["id"]
    await test_client.post(f"/v1/playlists/{pl_id}/songs", json={"song_uuid": sample_song.uuid}, cookies=cookies)
    resp = await test_client.post(f"/v1/playlists/{pl_id}/songs", json={"song_uuid": sample_song.uuid}, cookies=cookies)
    assert resp.status_code == 409
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_add_nonexistent_song(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    create = await test_client.post("/v1/playlists", json={"name": "bad song"}, cookies=cookies)
    pl_id = create.json()["id"]
    resp = await test_client.post(f"/v1/playlists/{pl_id}/songs", json={"song_uuid": "00000000-0000-0000-0000-000000000000"}, cookies=cookies)
    assert resp.status_code == 404
    # cleanup
    await test_client.delete(f"/v1/playlists/{pl_id}", cookies=cookies)


async def test_remove_song_from_playlist(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    create = await test_client.post("/v1/playlists", json={"name": "remove song"}, cookies=cookies)
    pl_id = create.json()["id"]
    await test_client.post(f"/v1/playlists/{pl_id}/songs", json={"song_uuid": sample_song.uuid}, cookies=cookies)
    resp = await test_client.delete(f"/v1/playlists/{pl_id}/songs/{sample_song.uuid}", cookies=cookies)
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
    create = await test_client.post("/v1/playlists", json={"name": "reorder"}, cookies=cookies)
    pl_id = create.json()["id"]
    await test_client.post(f"/v1/playlists/{pl_id}/songs", json={"song_uuid": sample_song.uuid}, cookies=cookies)
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
