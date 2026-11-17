"""Who may tag a song and replace its art.

A song with no owner is shared. Anyone may tag it the first time and give it its
first art; after that retagging it or replacing its art needs an admin. An owner
keeps full rights on their own song.
"""

import io
import os
import shutil
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image
from songbirdapi import crud
from songbirdapi.models import Role, Song, User
from songbirdapi.routes import AUTH_LOGIN, PROPERTIES, song_artwork_path, song_path
from songbirdapi.security import hash_password
from songbirdapi.settings import SongbirdServerConfig

from .conftest import _TestingSession

pytestmark = pytest.mark.asyncio(loop_scope="session")

PROPS = {
    "trackName": "Test",
    "artistName": "Artist",
    "collectionName": "Album",
    "artworkUrl100": "",
    "primaryGenreName": "Pop",
    "trackNumber": 1,
    "trackCount": 10,
    "collectionId": "12345",
    "discNumber": 1,
    "discCount": 1,
    "releaseDate": "2020-01-01",
    "releaseDateKey": "2020-01-01",
}


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def fake_taggers(monkeypatch):
    """The taggers write real files; these tests are about who may call them."""
    from songbirdapi.routers import properties

    for name in (
        "mp3ID3Tagger",
        "m4a_tagger",
        "mp3ID3TaggerNoArtwork",
        "m4aID3TaggerNoArtwork",
    ):
        monkeypatch.setattr(properties.itunes, name, lambda *a, **k: True)


async def _song(owner_id: str | None, tagged: bool, with_art: bool) -> Song:
    suffix = uuid.uuid4().hex
    path = f"/tmp/tag-rights-{suffix}.mp3"
    open(path, "wb").close()
    async with _TestingSession() as db:
        song = Song(
            uuid=str(uuid.uuid4()),
            url=f"https://example.com/{suffix}",
            file_path=path,
            owner_id=owner_id,
        )
        await crud.insert_song(db, song)
        if tagged:
            await crud.update_song_properties(db, song.uuid, PROPS, mark_tagged=True)
        if with_art:
            await crud.update_song_artwork(db, song.uuid, "t.jpg", "f.jpg")
    return song


async def _drop(song: Song):
    async with _TestingSession() as db:
        await crud.delete_song(db, song.uuid)
    os.remove(song.file_path) if os.path.exists(song.file_path) else None
    shutil.rmtree(
        os.path.join(SongbirdServerConfig().artwork_dir, song.uuid),  # pyright: ignore
        ignore_errors=True,
    )


@pytest_asyncio.fixture
async def owner(test_client):
    async with _TestingSession() as db:
        user = User(
            id=str(uuid.uuid4()),
            username=f"owner_{uuid.uuid4().hex[:6]}",
            email=f"owner_{uuid.uuid4().hex[:6]}@test.com",
            hashed_password=await hash_password("testpass123"),
            role=Role.user,
        )
        await crud.create_user(db, user)
    yield user
    async with _TestingSession() as db:
        await crud.delete_user(db, user.id)


@pytest_asyncio.fixture
async def shared_untagged():
    song = await _song(None, tagged=False, with_art=False)
    yield song
    await _drop(song)


@pytest_asyncio.fixture
async def shared_tagged():
    song = await _song(None, tagged=True, with_art=True)
    yield song
    await _drop(song)


async def _tag(test_client, user, song):
    cookies = await login(test_client, user)
    return await test_client.put(
        PROPERTIES,
        json={"song_id": song.uuid, "properties": PROPS},
        cookies=cookies,
    )


async def _upload(test_client, user, song):
    cookies = await login(test_client, user)
    return await test_client.post(
        song_artwork_path(song.uuid),
        files={"file": ("art.jpg", _jpeg(), "image/jpeg")},
        cookies=cookies,
    )


async def _tagged_at(song):
    async with _TestingSession() as db:
        row = await crud.get_song(db, song.uuid)
        return row.tagged_at


# --- tagging --------------------------------------------------------------


async def test_non_admin_may_apply_the_first_tag_to_a_shared_song(
    test_client, regular_user, shared_untagged
):
    assert await _tagged_at(shared_untagged) is None
    resp = await _tag(test_client, regular_user, shared_untagged)
    assert resp.status_code == 200
    assert await _tagged_at(shared_untagged) is not None


async def test_non_admin_cannot_retag_a_tagged_shared_song(
    test_client, regular_user, shared_tagged
):
    before = await _tagged_at(shared_tagged)
    resp = await _tag(test_client, regular_user, shared_tagged)
    assert resp.status_code == 403
    assert await _tagged_at(shared_tagged) == before


async def test_retag_with_new_art_url_is_also_refused(
    test_client, regular_user, shared_tagged
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        PROPERTIES,
        json={
            "song_id": shared_tagged.uuid,
            "properties": {**PROPS, "artworkUrl100": "https://example.com/new.jpg"},
        },
        cookies=cookies,
    )
    assert resp.status_code == 403


async def test_admin_may_retag_a_tagged_shared_song(
    test_client, admin_user, shared_tagged
):
    resp = await _tag(test_client, admin_user, shared_tagged)
    assert resp.status_code == 200


async def test_owner_may_retag_their_own_song(test_client, owner):
    song = await _song(owner.id, tagged=True, with_art=True)
    try:
        resp = await _tag(test_client, owner, song)
        assert resp.status_code == 200
    finally:
        await _drop(song)


async def test_non_owner_cannot_tag_a_song_owned_by_someone_else(
    test_client, regular_user, owner
):
    song = await _song(owner.id, tagged=False, with_art=False)
    try:
        resp = await _tag(test_client, regular_user, song)
        assert resp.status_code == 403
    finally:
        await _drop(song)


async def test_admin_may_tag_a_song_owned_by_someone_else(
    test_client, admin_user, owner
):
    song = await _song(owner.id, tagged=True, with_art=True)
    try:
        resp = await _tag(test_client, admin_user, song)
        assert resp.status_code == 200
    finally:
        await _drop(song)


# --- art ------------------------------------------------------------------


async def test_non_admin_may_give_a_shared_song_its_first_art(
    test_client, regular_user, shared_untagged
):
    resp = await _upload(test_client, regular_user, shared_untagged)
    assert resp.status_code == 200


async def test_non_admin_cannot_replace_the_art_of_a_shared_song(
    test_client, regular_user, shared_tagged
):
    resp = await _upload(test_client, regular_user, shared_tagged)
    assert resp.status_code == 403


async def test_a_refused_replace_leaves_the_art_version_alone(
    test_client, regular_user, shared_tagged
):
    cookies = await login(test_client, regular_user)
    before = (
        await test_client.get(song_path(shared_tagged.uuid), cookies=cookies)
    ).json()["artwork_updated_at"]
    await _upload(test_client, regular_user, shared_tagged)
    after = (
        await test_client.get(song_path(shared_tagged.uuid), cookies=cookies)
    ).json()["artwork_updated_at"]
    assert after == before


async def test_admin_may_replace_the_art_of_a_shared_song(
    test_client, admin_user, shared_tagged
):
    resp = await _upload(test_client, admin_user, shared_tagged)
    assert resp.status_code == 200


async def test_owner_may_replace_the_art_of_their_own_song(test_client, owner):
    song = await _song(owner.id, tagged=True, with_art=True)
    try:
        resp = await _upload(test_client, owner, song)
        assert resp.status_code == 200
    finally:
        await _drop(song)


async def test_non_owner_cannot_replace_art_of_a_song_owned_by_someone_else(
    test_client, regular_user, owner
):
    song = await _song(owner.id, tagged=False, with_art=True)
    try:
        resp = await _upload(test_client, regular_user, song)
        assert resp.status_code == 403
    finally:
        await _drop(song)


# --- publish, race, failed tag ----------------------------------------------


async def test_publishing_counts_as_the_first_tag(test_client, regular_user):
    song = await _song(regular_user.id, tagged=False, with_art=False)
    try:
        async with _TestingSession() as db:
            await crud.publish_song(db, song.uuid)
        assert await _tagged_at(song) is not None
        resp = await _tag(test_client, regular_user, song)
        assert resp.status_code == 403
    finally:
        await _drop(song)


async def test_two_first_tags_racing_let_exactly_one_through(
    test_client, regular_user, shared_untagged
):
    import asyncio

    results = await asyncio.gather(
        _tag(test_client, regular_user, shared_untagged),
        _tag(test_client, regular_user, shared_untagged),
    )
    assert sorted(r.status_code for r in results) == [200, 403]


async def test_a_failed_first_tag_hands_the_claim_back(
    test_client, regular_user, shared_untagged, monkeypatch
):
    from songbirdapi.routers import properties

    for name in ("mp3ID3TaggerNoArtwork", "m4aID3TaggerNoArtwork"):
        monkeypatch.setattr(properties.itunes, name, lambda *a, **k: False)
    resp = await _tag(test_client, regular_user, shared_untagged)
    assert resp.status_code == 500
    assert await _tagged_at(shared_untagged) is None


async def test_non_admin_cannot_tag_a_song_owned_by_someone_else_even_if_untagged(
    test_client, regular_user, owner
):
    song = await _song(owner.id, tagged=False, with_art=False)
    try:
        resp = await _tag(test_client, regular_user, song)
        assert resp.status_code == 403
    finally:
        await _drop(song)
