import pytest
from httpx import AsyncClient

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
        "/v1/auth/login", json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


async def test_save_draft(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        f"/v1/edit/songs/{sample_song.uuid}/draft", json=_EDIT_PARAMS, cookies=cookies
    )
    assert resp.status_code in (200, 204)


async def test_get_draft(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.put(
        f"/v1/edit/songs/{sample_song.uuid}/draft", json=_EDIT_PARAMS, cookies=cookies
    )
    resp = await test_client.get(
        f"/v1/edit/songs/{sample_song.uuid}/draft", cookies=cookies
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["params"]["trim_start"] == 0
    assert body["params"]["volume"] == 1.0
    assert "updated_at" in body


async def test_delete_draft(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    await test_client.put(
        f"/v1/edit/songs/{sample_song.uuid}/draft", json=_EDIT_PARAMS, cookies=cookies
    )
    resp = await test_client.delete(
        f"/v1/edit/songs/{sample_song.uuid}/draft", cookies=cookies
    )
    assert resp.status_code == 204


async def test_get_draft_after_delete_returns_404(
    test_client: AsyncClient, regular_user, sample_song
):
    cookies = await login(test_client, regular_user)
    await test_client.put(
        f"/v1/edit/songs/{sample_song.uuid}/draft", json=_EDIT_PARAMS, cookies=cookies
    )
    await test_client.delete(
        f"/v1/edit/songs/{sample_song.uuid}/draft", cookies=cookies
    )
    resp = await test_client.get(
        f"/v1/edit/songs/{sample_song.uuid}/draft", cookies=cookies
    )
    assert resp.status_code == 404


async def test_create_edit_job(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        f"/v1/edit/songs/{sample_song.uuid}",
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
        f"/v1/edit/songs/{sample_song.uuid}",
        json={"params": _EDIT_PARAMS, "overwrite": False},
        cookies=cookies,
    )
    job_id = create_resp.json()["job_id"]
    resp = await test_client.get(f"/v1/edit/jobs/{job_id}", cookies=cookies)
    assert resp.status_code == 200
    assert "status" in resp.json()
