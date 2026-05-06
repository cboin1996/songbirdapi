import pytest
from httpx import AsyncClient
from songbirdapi.routes import AUTH_LOGIN, SONGS, SONGS_LIBRARY, library_song_path, song_artwork_path, song_path, song_play_path, songs_explore_path

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


async def test_list_songs_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(SONGS)
    assert resp.status_code == 401


async def test_list_songs(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(SONGS, cookies=cookies)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_library_songs_contains_uuid(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    resp = await test_client.get(SONGS_LIBRARY, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(e["uuid"] == sample_song.uuid for e in body)


async def test_record_play(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(song_play_path(sample_song.uuid), cookies=cookies)
    assert resp.status_code in (200, 204)


async def test_explore_week(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(songs_explore_path("week"), cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "most_played" in body
    assert "recently_added" in body


async def test_explore_day(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(songs_explore_path("day"), cookies=cookies)
    assert resp.status_code == 200


async def test_explore_all(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(songs_explore_path("all"), cookies=cookies)
    assert resp.status_code == 200


async def test_explore_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(songs_explore_path("week"))
    assert resp.status_code == 401


async def test_record_play_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.post(song_play_path(sample_song.uuid))
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /{id}/artwork
# ---------------------------------------------------------------------------


async def test_get_artwork_not_found_song(test_client: AsyncClient):
    resp = await test_client.get(
        song_artwork_path("00000000-0000-0000-0000-000000000000", "full")
    )
    assert resp.status_code == 404


async def test_get_artwork_no_cached_artwork(test_client: AsyncClient, sample_song):
    # sample_song has no artwork cached
    resp = await test_client.get(song_artwork_path(sample_song.uuid, "full"))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /{id}/artwork
# ---------------------------------------------------------------------------


async def test_upload_artwork_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.post(
        song_artwork_path(sample_song.uuid),
        files={"file": ("art.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, "image/jpeg")},
    )
    assert resp.status_code == 401


async def test_upload_artwork_song_not_found(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        song_artwork_path("00000000-0000-0000-0000-000000000000"),
        files={"file": ("art.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, "image/jpeg")},
        cookies=cookies,
    )
    assert resp.status_code == 404


async def test_upload_artwork_invalid_file(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        song_artwork_path(sample_song.uuid),
        files={"file": ("art.txt", b"not an image", "text/plain")},
        cookies=cookies,
    )
    assert resp.status_code == 400
