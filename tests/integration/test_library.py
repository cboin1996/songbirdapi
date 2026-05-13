import uuid as _uuid

import pytest
from httpx import AsyncClient
from songbirdapi.routes import (
    AUTH_LOGIN,
    LIBRARY,
    LIBRARY_BULK,
    LIBRARY_OFFLINE,
    LIBRARY_PUBLISH,
    library_offline_path,
    library_position_path,
    library_restore_path,
    library_song_path,
    song_path,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


async def test_library_empty_on_start(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(LIBRARY, cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_add_to_library(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    assert resp.status_code == 201
    body = resp.json()
    assert body["song_id"] == sample_song.uuid
    assert body["last_position"] == 0.0
    assert body["last_played_at"] is None


async def test_add_to_library_idempotent(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    resp = await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    assert resp.status_code == 201


async def test_add_nonexistent_song_returns_404(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(library_song_path("does-not-exist"), cookies=cookies)
    assert resp.status_code == 404


async def test_library_contains_added_song(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    resp = await test_client.get(LIBRARY, cookies=cookies)
    assert resp.status_code == 200
    assert any(e["song_id"] == sample_song.uuid for e in resp.json())


async def test_remove_from_library(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    resp = await test_client.delete(
        library_song_path(sample_song.uuid), cookies=cookies
    )
    assert resp.status_code == 204
    resp = await test_client.get(LIBRARY, cookies=cookies)
    assert not any(e["song_id"] == sample_song.uuid for e in resp.json())


async def test_remove_from_library_cleans_offline(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    await test_client.post(library_offline_path(sample_song.uuid), cookies=cookies)
    resp = await test_client.get(LIBRARY_OFFLINE, cookies=cookies)
    assert sample_song.uuid in resp.json()

    await test_client.delete(library_song_path(sample_song.uuid), cookies=cookies)
    resp = await test_client.get(LIBRARY_OFFLINE, cookies=cookies)
    assert sample_song.uuid not in resp.json()


async def test_remove_nonexistent_returns_404(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.delete(
        library_song_path("does-not-exist"), cookies=cookies
    )
    assert resp.status_code == 404


async def test_update_position(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    resp = await test_client.patch(
        library_position_path(sample_song.uuid),
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
        library_position_path("00000000-0000-0000-0000-000000000000"),
        json={"position": 10.0},
        cookies=cookies,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


async def test_get_library_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(LIBRARY)
    assert resp.status_code == 401


async def test_add_to_library_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.post(library_song_path(sample_song.uuid))
    assert resp.status_code == 401


async def test_remove_from_library_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.delete(library_song_path(sample_song.uuid))
    assert resp.status_code == 401


async def test_update_position_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.patch(
        library_position_path(sample_song.uuid), json={"position": 0.0}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /publish
# ---------------------------------------------------------------------------


async def test_publish_requires_auth(test_client: AsyncClient):
    resp = await test_client.post(LIBRARY_PUBLISH)
    assert resp.status_code == 401


async def test_publish_returns_count(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        LIBRARY_PUBLISH, json={"song_ids": []}, cookies=cookies
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
    await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    await test_client.post(library_song_path(second_uuid), cookies=cookies)
    # bulk remove both
    resp = await test_client.request(
        "DELETE",
        LIBRARY_BULK,
        json={"song_ids": [sample_song.uuid, second_uuid]},
        cookies=cookies,
    )
    assert resp.status_code == 204
    lib = await test_client.get(LIBRARY, cookies=cookies)
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
    await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    await test_client.post(library_song_path(second_uuid), cookies=cookies)
    await test_client.post(library_offline_path(sample_song.uuid), cookies=cookies)
    await test_client.post(library_offline_path(second_uuid), cookies=cookies)

    resp = await test_client.request(
        "DELETE",
        LIBRARY_BULK,
        json={"song_ids": [sample_song.uuid, second_uuid]},
        cookies=cookies,
    )
    assert resp.status_code == 204
    resp = await test_client.get(LIBRARY_OFFLINE, cookies=cookies)
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
    await test_client.post(library_song_path(sample_song.uuid), cookies=cookies)
    await test_client.post(library_song_path(third_uuid), cookies=cookies)
    # bulk remove only third
    resp = await test_client.request(
        "DELETE",
        LIBRARY_BULK,
        json={"song_ids": [third_uuid]},
        cookies=cookies,
    )
    assert resp.status_code == 204
    lib = await test_client.get(LIBRARY, cookies=cookies)
    uuids = [e["song_id"] for e in lib.json()]
    assert third_uuid not in uuids
    assert sample_song.uuid in uuids
    # cleanup
    await test_client.request(
        "DELETE",
        LIBRARY_BULK,
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
        "DELETE", LIBRARY_BULK, json={"song_ids": []}, cookies=cookies
    )
    assert resp.status_code == 400


async def test_bulk_remove_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.request(
        "DELETE", LIBRARY_BULK, json={"song_ids": [sample_song.uuid]}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Publish chain cleanup
# ---------------------------------------------------------------------------


async def test_publish_nulls_owner_and_sets_community(
    test_client: AsyncClient, regular_user
):
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession

    cookies = await login(test_client, regular_user)
    song_id = str(_uuid.uuid4())
    async with _TestingSession() as db:
        await _crud.insert_song(
            db,
            _Song(
                uuid=song_id,
                url="https://example.com/pub1",
                file_path="/tmp/pub1.mp3",
                owner_id=regular_user.id,
            ),
        )
    await test_client.post(library_song_path(song_id), cookies=cookies)
    resp = await test_client.post(
        LIBRARY_PUBLISH, json={"song_ids": [song_id]}, cookies=cookies
    )
    assert resp.status_code == 200
    assert resp.json()["published"] == 1

    async with _TestingSession() as db:
        song = await _crud.get_song(db, song_id)
        assert song.owner_id is None
        assert song.source == "community"
        assert song.parent_song_id is None
        assert song.root_song_id is None
    # cleanup
    async with _TestingSession() as db:
        await _crud.delete_song(db, song_id)


async def test_publish_deletes_orphan_intermediates(
    test_client: AsyncClient, regular_user
):
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession

    cookies = await login(test_client, regular_user)
    root_id = str(_uuid.uuid4())
    mid_id = str(_uuid.uuid4())
    leaf_id = str(_uuid.uuid4())
    async with _TestingSession() as db:
        await _crud.insert_song(
            db,
            _Song(
                uuid=root_id, url="https://example.com/root", file_path="/tmp/root.mp3"
            ),
        )
        await _crud.insert_song(
            db,
            _Song(
                uuid=mid_id,
                url="https://example.com/mid",
                file_path="/tmp/mid.mp3",
                parent_song_id=root_id,
                root_song_id=root_id,
                owner_id=regular_user.id,
            ),
        )
        await _crud.insert_song(
            db,
            _Song(
                uuid=leaf_id,
                url="https://example.com/leaf",
                file_path="/tmp/leaf.mp3",
                parent_song_id=mid_id,
                root_song_id=root_id,
                owner_id=regular_user.id,
            ),
        )
    await test_client.post(library_song_path(leaf_id), cookies=cookies)
    resp = await test_client.post(
        LIBRARY_PUBLISH, json={"song_ids": [leaf_id]}, cookies=cookies
    )
    assert resp.status_code == 200

    async with _TestingSession() as db:
        # mid should be deleted (orphaned intermediate)
        assert await _crud.get_song(db, mid_id) is None
        # root still exists
        assert await _crud.get_song(db, root_id) is not None
    # cleanup
    async with _TestingSession() as db:
        await _crud.delete_song(db, leaf_id)
        await _crud.delete_song(db, root_id)


async def test_publish_deletes_drafts(test_client: AsyncClient, regular_user):
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession
    from songbirdapi.routes import edit_draft_path

    cookies = await login(test_client, regular_user)
    song_id = str(_uuid.uuid4())
    async with _TestingSession() as db:
        await _crud.insert_song(
            db,
            _Song(
                uuid=song_id,
                url="https://example.com/pubdraft",
                file_path="/tmp/pubdraft.mp3",
                owner_id=regular_user.id,
            ),
        )
    await test_client.post(library_song_path(song_id), cookies=cookies)
    # save a draft
    params = {
        "trim_start": 0,
        "trim_end": None,
        "volume": 1.0,
        "fades": [],
        "speed": 1.0,
        "normalize": False,
        "cuts": [],
    }
    await test_client.put(edit_draft_path(song_id), json=params, cookies=cookies)
    # publish
    await test_client.post(
        LIBRARY_PUBLISH, json={"song_ids": [song_id]}, cookies=cookies
    )
    # draft should be gone
    async with _TestingSession() as db:
        draft = await _crud.get_edit_draft(db, regular_user.id, song_id)
        assert draft is None
    # cleanup
    async with _TestingSession() as db:
        await _crud.delete_song(db, song_id)


# ---------------------------------------------------------------------------
# Restore endpoint
# ---------------------------------------------------------------------------


async def test_restore_swaps_library_entry(test_client: AsyncClient, regular_user):
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession

    cookies = await login(test_client, regular_user)
    root_id = str(_uuid.uuid4())
    child_id = str(_uuid.uuid4())
    async with _TestingSession() as db:
        await _crud.insert_song(
            db,
            _Song(
                uuid=root_id,
                url="https://example.com/restore-root",
                file_path="/tmp/rr.mp3",
            ),
        )
        await _crud.insert_song(
            db,
            _Song(
                uuid=child_id,
                url="https://example.com/restore-child",
                file_path="/tmp/rc.mp3",
                parent_song_id=root_id,
                root_song_id=root_id,
                owner_id=regular_user.id,
            ),
        )
    await test_client.post(library_song_path(child_id), cookies=cookies)
    resp = await test_client.post(
        library_restore_path(child_id),
        json={"target": root_id},
        cookies=cookies,
    )
    assert resp.status_code == 204

    # library should now have root, not child
    lib = await test_client.get(LIBRARY, cookies=cookies)
    ids = [e["song_id"] for e in lib.json()]
    assert root_id in ids
    assert child_id not in ids

    # child should have been deleted (orphan)
    async with _TestingSession() as db:
        assert await _crud.get_song(db, child_id) is None
    # cleanup
    await test_client.delete(library_song_path(root_id), cookies=cookies)
    async with _TestingSession() as db:
        await _crud.delete_song(db, root_id)


async def test_restore_cleans_drafts(test_client: AsyncClient, regular_user):
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession
    from songbirdapi.routes import edit_draft_path

    cookies = await login(test_client, regular_user)
    root_id = str(_uuid.uuid4())
    child_id = str(_uuid.uuid4())
    async with _TestingSession() as db:
        await _crud.insert_song(
            db,
            _Song(
                uuid=root_id,
                url="https://example.com/restore-draft-root",
                file_path="/tmp/rdr.mp3",
            ),
        )
        await _crud.insert_song(
            db,
            _Song(
                uuid=child_id,
                url="https://example.com/restore-draft-child",
                file_path="/tmp/rdc.mp3",
                parent_song_id=root_id,
                root_song_id=root_id,
                owner_id=regular_user.id,
            ),
        )
    await test_client.post(library_song_path(child_id), cookies=cookies)
    # save drafts on both
    params = {
        "trim_start": 0,
        "trim_end": None,
        "volume": 1.0,
        "fades": [],
        "speed": 1.0,
        "normalize": False,
        "cuts": [],
    }
    await test_client.put(edit_draft_path(child_id), json=params, cookies=cookies)
    # Need root in library temporarily to save a draft on it
    await test_client.post(library_song_path(root_id), cookies=cookies)
    await test_client.put(edit_draft_path(root_id), json=params, cookies=cookies)
    await test_client.delete(library_song_path(root_id), cookies=cookies)

    await test_client.post(
        library_restore_path(child_id),
        json={"target": root_id},
        cookies=cookies,
    )
    # source draft gone, target draft preserved (for revert-to-last-save UX)
    async with _TestingSession() as db:
        assert await _crud.get_edit_draft(db, regular_user.id, child_id) is None
        assert await _crud.get_edit_draft(db, regular_user.id, root_id) is not None
    # cleanup
    await test_client.delete(library_song_path(root_id), cookies=cookies)
    async with _TestingSession() as db:
        await _crud.delete_song(db, root_id)


async def test_restore_not_owned_returns_404(test_client: AsyncClient, regular_user):
    from songbirdapi import crud as _crud
    from songbirdapi.models import Song as _Song
    from tests.integration.conftest import _TestingSession

    cookies = await login(test_client, regular_user)
    song_id = str(_uuid.uuid4())
    async with _TestingSession() as db:
        await _crud.insert_song(
            db,
            _Song(
                uuid=song_id,
                url="https://example.com/restore-notown",
                file_path="/tmp/rno.mp3",
            ),
        )
    resp = await test_client.post(
        library_restore_path(song_id),
        json={"target": song_id},
        cookies=cookies,
    )
    assert resp.status_code == 404
    # cleanup
    async with _TestingSession() as db:
        await _crud.delete_song(db, song_id)


async def test_restore_nonexistent_song_returns_404(
    test_client: AsyncClient, regular_user
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        library_restore_path("00000000-0000-0000-0000-000000000000"),
        json={"target": "00000000-0000-0000-0000-000000000001"},
        cookies=cookies,
    )
    assert resp.status_code == 404


async def test_restore_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.post(
        library_restore_path(sample_song.uuid),
        json={"target": sample_song.uuid},
    )
    assert resp.status_code == 401
