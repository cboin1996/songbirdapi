import io
import os
import shutil
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image
from songbirdapi import crud
from songbirdapi.models import Song
from songbirdapi.routes import (
    AUTH_LOGIN,
    SONGS_LIBRARY,
    PLAYLISTS,
    library_song_path,
    playlist_songs_path,
    share_info_path,
    share_song_path,
    song_artwork_path,
    song_path,
)
from songbirdapi.settings import SongbirdServerConfig

from .conftest import _TestingSession

pytestmark = pytest.mark.asyncio(loop_scope="session")

IMMUTABLE = "private, max-age=31536000, immutable"


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


def _jpeg(color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, "JPEG")
    return buf.getvalue()


@pytest_asyncio.fixture
async def art_song(test_client):
    """A song of its own: the shared fixtures must stay without art."""
    async with _TestingSession() as db:
        song = Song(
            uuid=str(uuid.uuid4()),
            url=f"https://example.com/{uuid.uuid4().hex}",
            file_path="/tmp/art-song.mp3",
        )
        await crud.insert_song(db, song)
    yield song
    async with _TestingSession() as db:
        await crud.delete_song(db, song.uuid)
    shutil.rmtree(
        os.path.join(SongbirdServerConfig().artwork_dir, song.uuid),  # pyright: ignore
        ignore_errors=True,
    )


async def _upload(test_client, user, song, color: str):
    cookies = await login(test_client, user)
    resp = await test_client.post(
        song_artwork_path(song.uuid),
        files={"file": ("art.jpg", _jpeg(color), "image/jpeg")},
        cookies=cookies,
    )
    assert resp.status_code == 200
    return cookies


async def _version(test_client, cookies, song) -> int | None:
    resp = await test_client.get(song_path(song.uuid), cookies=cookies)
    assert resp.status_code == 200
    return resp.json()["artwork_updated_at"]


async def test_song_without_art_writes_has_no_version(
    test_client, regular_user, art_song
):
    cookies = await login(test_client, regular_user)
    assert await _version(test_client, cookies, art_song) is None


async def test_every_art_write_moves_the_version_forward_in_milliseconds(
    test_client, regular_user, admin_user, art_song
):
    import time

    before = int(time.time() * 1000)
    cookies = await _upload(test_client, regular_user, art_song, "red")
    first = await _version(test_client, cookies, art_song)
    assert first is not None and before <= first <= int(time.time() * 1000) + 1000

    # Replacing art on a shared song is for admins.
    await _upload(test_client, admin_user, art_song, "blue")
    second = await _version(test_client, cookies, art_song)
    assert second > first  # two writes in the same millisecond still differ


async def test_versioned_route_serves_current_art_immutably(
    test_client, regular_user, art_song
):
    cookies = await _upload(test_client, regular_user, art_song, "red")
    version = await _version(test_client, cookies, art_song)

    resp = await test_client.get(song_artwork_path(art_song.uuid, "thumb", version))

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["cache-control"] == IMMUTABLE


async def test_versioned_route_serves_whatever_the_version_segment_says(
    test_client, regular_user, art_song
):
    await _upload(test_client, regular_user, art_song, "red")

    stale = await test_client.get(song_artwork_path(art_song.uuid, "full", 1))
    zero = await test_client.get(song_artwork_path(art_song.uuid, "full", 0))

    assert stale.status_code == 200 and zero.status_code == 200
    assert stale.content == zero.content
    assert zero.headers["cache-control"] == IMMUTABLE


async def test_versioned_route_for_a_song_without_art_is_404(test_client, art_song):
    resp = await test_client.get(song_artwork_path(art_song.uuid, "thumb", 0))
    assert resp.status_code == 404


async def test_unversioned_route_is_unchanged(test_client, regular_user, art_song):
    await _upload(test_client, regular_user, art_song, "red")

    resp = await test_client.get(song_artwork_path(art_song.uuid, "thumb"))

    assert resp.status_code == 200
    assert "immutable" not in resp.headers.get("cache-control", "")


async def test_library_payload_carries_the_version(test_client, regular_user, art_song):
    cookies = await _upload(test_client, regular_user, art_song, "red")
    version = await _version(test_client, cookies, art_song)
    add = await test_client.post(library_song_path(art_song.uuid), cookies=cookies)
    assert add.status_code in (200, 201, 204)

    resp = await test_client.get(SONGS_LIBRARY, cookies=cookies)

    row = next(s for s in resp.json() if s["uuid"] == art_song.uuid)
    assert row["artwork_updated_at"] == version
    await test_client.delete(library_song_path(art_song.uuid), cookies=cookies)


async def test_share_info_and_versioned_share_art(test_client, regular_user, art_song):
    cookies = await _upload(test_client, regular_user, art_song, "red")
    version = await _version(test_client, cookies, art_song)
    token = (
        await test_client.post(share_song_path(art_song.uuid), cookies=cookies)
    ).json()["token"]

    info = (await test_client.get(share_info_path(token))).json()
    art = await test_client.get(f"/v1/share/{token}/artwork/thumb/{version}")
    plain = await test_client.get(f"/v1/share/{token}/artwork/thumb")

    assert info["artwork_updated_at"] == version
    assert art.status_code == 200
    assert art.headers["cache-control"] == IMMUTABLE
    assert plain.status_code == 200
    assert "immutable" not in plain.headers.get("cache-control", "")


async def test_edited_copy_keeps_its_own_art_files(
    test_client, regular_user, admin_user, art_song
):
    from songbirdapi.artwork import copy_artwork

    cookies = await _upload(test_client, regular_user, art_song, "red")
    async with _TestingSession() as db:
        src = await crud.get_song(db, art_song.uuid)
        src_thumb, src_full = src.artwork_thumb, src.artwork_full
    new_id = str(uuid.uuid4())
    artwork_dir = SongbirdServerConfig().artwork_dir  # pyright: ignore
    try:
        thumb, full = copy_artwork(src_thumb, src_full, new_id, artwork_dir)
        assert thumb != src_thumb and full != src_full
        before = open(thumb, "rb").read()
        await _upload(test_client, admin_user, art_song, "blue")
        assert open(thumb, "rb").read() == before
    finally:
        shutil.rmtree(os.path.join(artwork_dir, new_id), ignore_errors=True)


async def test_versioned_redirect_to_itunes_art_is_not_immutable(
    test_client, regular_user
):
    """The redirect target can change, so its answer must not be cached forever."""
    async with _TestingSession() as db:
        song = Song(
            uuid=str(uuid.uuid4()),
            url=f"https://example.com/{uuid.uuid4().hex}",
            file_path="/tmp/redirect-song.mp3",
            properties={"artworkUrl100": "https://is1.example.com/a/100x100bb.jpg"},
        )
        await crud.insert_song(db, song)
    try:
        resp = await test_client.get(
            song_artwork_path(song.uuid, "thumb", 0), follow_redirects=False
        )

        assert resp.status_code == 302
        assert resp.headers["location"] == "https://is1.example.com/a/200x200bb.jpg"
        assert "immutable" not in resp.headers.get("cache-control", "")
    finally:
        async with _TestingSession() as db:
            await crud.delete_song(db, song.uuid)


async def test_playlist_payload_carries_the_version(
    test_client, regular_user, art_song
):
    cookies = await _upload(test_client, regular_user, art_song, "red")
    version = await _version(test_client, cookies, art_song)
    made = await test_client.post(PLAYLISTS, json={"name": "art"}, cookies=cookies)
    assert made.status_code == 201
    pid = made.json()["id"]
    add = await test_client.post(
        playlist_songs_path(pid), json={"song_uuid": art_song.uuid}, cookies=cookies
    )
    assert add.status_code == 204

    resp = await test_client.get(playlist_songs_path(pid), cookies=cookies)

    row = next(s for s in resp.json() if s["uuid"] == art_song.uuid)
    assert row["artwork_updated_at"] == version
    await test_client.delete(f"{PLAYLISTS}/{pid}", cookies=cookies)
