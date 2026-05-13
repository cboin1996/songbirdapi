import uuid as _uuid

import pytest
from httpx import AsyncClient
from songbirdapi.routes import (
    AUTH_LOGIN,
    EDIT_DRAFTS,
    edit_draft_path,
    edit_job_path,
    edit_song_path,
    song_path,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

_EDIT_PARAMS = {
    "trim_start": 0,
    "trim_end": None,
    "volume": 1.0,
    "fades": [],
    "speed": 1.0,
    "normalize": False,
    "cuts": [],
}


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


async def test_save_draft(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        edit_draft_path(sample_song.uuid), json=_EDIT_PARAMS, cookies=cookies
    )
    assert resp.status_code in (200, 204)


async def test_get_draft(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.put(
        edit_draft_path(sample_song.uuid), json=_EDIT_PARAMS, cookies=cookies
    )
    resp = await test_client.get(edit_draft_path(sample_song.uuid), cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["params"]["trim_start"] == 0
    assert body["params"]["volume"] == 1.0
    assert "updated_at" in body


async def test_delete_draft(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.put(
        edit_draft_path(sample_song.uuid), json=_EDIT_PARAMS, cookies=cookies
    )
    resp = await test_client.delete(edit_draft_path(sample_song.uuid), cookies=cookies)
    assert resp.status_code == 204


async def test_get_draft_after_delete_returns_404(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await test_client.put(
        edit_draft_path(sample_song.uuid), json=_EDIT_PARAMS, cookies=cookies
    )
    await test_client.delete(edit_draft_path(sample_song.uuid), cookies=cookies)
    resp = await test_client.get(edit_draft_path(sample_song.uuid), cookies=cookies)
    assert resp.status_code == 404


async def test_create_edit_job(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        edit_song_path(sample_song.uuid),
        json={"params": _EDIT_PARAMS, "overwrite": False},
        cookies=cookies,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert "status" in body


async def test_get_edit_job(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    create_resp = await test_client.post(
        edit_song_path(sample_song.uuid),
        json={"params": _EDIT_PARAMS, "overwrite": False},
        cookies=cookies,
    )
    job_id = create_resp.json()["job_id"]
    resp = await test_client.get(edit_job_path(job_id), cookies=cookies)
    assert resp.status_code == 200
    assert "status" in resp.json()


async def test_edit_job_lossless_field(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    create_resp = await test_client.post(
        edit_song_path(sample_song.uuid),
        json={"params": _EDIT_PARAMS, "overwrite": False},
        cookies=cookies,
    )
    job_id = create_resp.json()["job_id"]
    resp = await test_client.get(edit_job_path(job_id), cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "lossless" in body
    # default params (no volume/speed/fade changes) should be lossless-eligible
    assert body["lossless"] is True


# ---------------------------------------------------------------------------
# crud.child_ref_count with exclude param
# ---------------------------------------------------------------------------


async def test_child_ref_count_exclude(test_client: AsyncClient):
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession

    parent_id = str(_uuid.uuid4())
    child1_id = str(_uuid.uuid4())
    child2_id = str(_uuid.uuid4())
    async with _TestingSession() as db:
        await _crud.insert_song(
            db,
            _Song(
                uuid=parent_id, url="https://example.com/parent", file_path="/tmp/p.mp3"
            ),
        )
        await _crud.insert_song(
            db,
            _Song(
                uuid=child1_id,
                url="https://example.com/c1",
                file_path="/tmp/c1.mp3",
                parent_song_id=parent_id,
            ),
        )
        await _crud.insert_song(
            db,
            _Song(
                uuid=child2_id,
                url="https://example.com/c2",
                file_path="/tmp/c2.mp3",
                parent_song_id=parent_id,
            ),
        )
    async with _TestingSession() as db:
        assert await _crud.child_ref_count(db, parent_id) == 2
        assert await _crud.child_ref_count(db, parent_id, exclude=child1_id) == 1
        assert await _crud.child_ref_count(db, parent_id, exclude=child2_id) == 1
    # cleanup
    async with _TestingSession() as db:
        await _crud.delete_song(db, child2_id)
        await _crud.delete_song(db, child1_id)
        await _crud.delete_song(db, parent_id)


# ---------------------------------------------------------------------------
# crud.delete_song cleans up drafts
# ---------------------------------------------------------------------------


async def test_delete_song_cleans_drafts(test_client: AsyncClient, regular_user):
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession

    song_id = str(_uuid.uuid4())
    async with _TestingSession() as db:
        await _crud.insert_song(
            db,
            _Song(
                uuid=song_id,
                url="https://example.com/draft-del",
                file_path="/tmp/dd.mp3",
            ),
        )
        await _crud.upsert_edit_draft(db, regular_user.id, song_id, _EDIT_PARAMS)
        draft = await _crud.get_edit_draft(db, regular_user.id, song_id)
        assert draft is not None
        await _crud.delete_song(db, song_id)
        draft = await _crud.get_edit_draft(db, regular_user.id, song_id)
        assert draft is None


# ---------------------------------------------------------------------------
# crud.list_user_drafts only returns drafts for songs in user's library
# ---------------------------------------------------------------------------


async def test_list_user_drafts_requires_library(
    test_client: AsyncClient, regular_user, sample_song
):
    from songbirdapi import crud as _crud
    from tests.integration.conftest import _TestingSession

    cookies = await login(test_client, regular_user)
    # save a draft
    await test_client.put(
        edit_draft_path(sample_song.uuid), json=_EDIT_PARAMS, cookies=cookies
    )
    # NOT in library -> draft should not appear in list
    async with _TestingSession() as db:
        await _crud.remove_from_library(db, regular_user.id, sample_song.uuid)
    resp = await test_client.get(EDIT_DRAFTS, cookies=cookies)
    assert resp.status_code == 200
    ids = [d["song_id"] for d in resp.json()]
    assert sample_song.uuid not in ids

    # Add to library -> draft should appear
    from songbirdapi.routes import library_song_path

    await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    resp = await test_client.get(EDIT_DRAFTS, cookies=cookies)
    assert resp.status_code == 200
    ids = [d["song_id"] for d in resp.json()]
    assert sample_song.uuid in ids
    # cleanup draft + library entry
    await test_client.delete(edit_draft_path(sample_song.uuid), cookies=cookies)
    await test_client.delete(library_song_path(sample_song.uuid), cookies=cookies)
