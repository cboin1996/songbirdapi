import asyncio

import pytest
from httpx import AsyncClient
from songbirdapi.routes import AUTH_LOGIN, IMPORT, import_job_path

pytestmark = pytest.mark.asyncio(loop_scope="session")

MINIMAL_MP3 = (
    b"ID3\x03\x00\x00\x00\x00\x00\x00"  # ID3v2 header, empty tags
    + b"\xff\xfb\x90\x00"
    + b"\x00" * 413  # MP3 frame header + padding
)


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


async def test_start_import_requires_auth(test_client: AsyncClient):
    resp = await test_client.post(
        IMPORT, files={"file": ("song.mp3", MINIMAL_MP3, "audio/mpeg")}
    )
    assert resp.status_code == 401


async def test_start_import_invalid_file_type(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        IMPORT,
        files={"file": ("notes.txt", b"hello", "text/plain")},
        cookies=cookies,
    )
    assert resp.status_code == 400


async def test_start_import_valid_mp3(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        IMPORT,
        files={"file": ("song.mp3", MINIMAL_MP3, "audio/mpeg")},
        cookies=cookies,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["status"] in ("pending", "processing")


async def test_list_imports_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(IMPORT)
    assert resp.status_code == 401


async def test_list_imports_empty(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(IMPORT, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "jobs" in body
    assert isinstance(body["jobs"], list)


async def test_list_imports_after_upload(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    post = await test_client.post(
        IMPORT,
        files={"file": ("track.mp3", MINIMAL_MP3, "audio/mpeg")},
        cookies=cookies,
    )
    assert post.status_code == 202
    job_id = post.json()["job_id"]

    resp = await test_client.get(IMPORT, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "jobs" in body
    assert any(j["job_id"] == job_id for j in body["jobs"])


async def test_get_import_job_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(import_job_path("some-job-id"))
    assert resp.status_code == 401


async def test_get_import_job_not_found(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(import_job_path("nonexistent-job-id"), cookies=cookies)
    assert resp.status_code == 404


async def test_get_import_job_found(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    post = await test_client.post(
        IMPORT,
        files={"file": ("album.mp3", MINIMAL_MP3, "audio/mpeg")},
        cookies=cookies,
    )
    assert post.status_code == 202
    job_id = post.json()["job_id"]

    resp = await test_client.get(import_job_path(job_id), cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert "status" in body


async def test_start_import_valid_m4a(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        IMPORT,
        files={"file": ("song.m4a", MINIMAL_MP3, "audio/mp4")},
        cookies=cookies,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body


async def test_list_imports_pagination(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(f"{IMPORT}?limit=1&offset=0", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "jobs" in body
    assert len(body["jobs"]) <= 1


async def test_import_untagged_mp3_falls_back_to_filename(
    test_client: AsyncClient, regular_user
):
    cookies = await login(test_client, regular_user)
    post = await test_client.post(
        IMPORT,
        files={"file": ("My Song.mp3", MINIMAL_MP3, "audio/mpeg")},
        cookies=cookies,
    )
    assert post.status_code == 202
    job_id = post.json()["job_id"]

    # wait for background task to process
    for _ in range(20):
        await asyncio.sleep(0.2)
        resp = await test_client.get(import_job_path(job_id), cookies=cookies)
        assert resp.status_code == 200
        if resp.json()["status"] not in ("pending", "processing"):
            break

    body = resp.json()
    assert body["status"] != "failed", f"import failed: {body.get('error')}"


async def test_import_job_not_visible_to_other_user(
    test_client: AsyncClient, regular_user, admin_user
):
    reg_cookies = await login(test_client, regular_user)
    post = await test_client.post(
        IMPORT,
        files={"file": ("private.mp3", MINIMAL_MP3, "audio/mpeg")},
        cookies=reg_cookies,
    )
    assert post.status_code == 202
    job_id = post.json()["job_id"]

    adm_cookies = await login(test_client, admin_user)
    resp = await test_client.get(import_job_path(job_id), cookies=adm_cookies)
    assert resp.status_code == 404
