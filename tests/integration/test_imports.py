import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")

MINIMAL_MP3 = (
    b'ID3\x03\x00\x00\x00\x00\x00\x00'  # ID3v2 header, empty tags
    + b'\xff\xfb\x90\x00' + b'\x00' * 413  # MP3 frame header + padding
)


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post("/v1/auth/login", json={"username": user.username, "password": "testpass123"})
    return dict(resp.cookies)


async def test_start_import_requires_auth(test_client: AsyncClient):
    resp = await test_client.post("/v1/import", files={"file": ("song.mp3", MINIMAL_MP3, "audio/mpeg")})
    assert resp.status_code == 401


async def test_start_import_invalid_file_type(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        "/v1/import",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        cookies=cookies,
    )
    assert resp.status_code == 400


async def test_start_import_valid_mp3(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        "/v1/import",
        files={"file": ("song.mp3", MINIMAL_MP3, "audio/mpeg")},
        cookies=cookies,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["status"] in ("pending", "processing")


async def test_list_imports_requires_auth(test_client: AsyncClient):
    resp = await test_client.get("/v1/import")
    assert resp.status_code == 401


async def test_list_imports_empty(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get("/v1/import", cookies=cookies)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_imports_after_upload(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    post = await test_client.post(
        "/v1/import",
        files={"file": ("track.mp3", MINIMAL_MP3, "audio/mpeg")},
        cookies=cookies,
    )
    assert post.status_code == 202
    job_id = post.json()["job_id"]

    resp = await test_client.get("/v1/import", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(j["job_id"] == job_id for j in body)


async def test_get_import_job_requires_auth(test_client: AsyncClient):
    resp = await test_client.get("/v1/import/some-job-id")
    assert resp.status_code == 401


async def test_get_import_job_not_found(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/import/nonexistent-job-id", cookies=cookies)
    assert resp.status_code == 404


async def test_get_import_job_found(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    post = await test_client.post(
        "/v1/import",
        files={"file": ("album.mp3", MINIMAL_MP3, "audio/mpeg")},
        cookies=cookies,
    )
    assert post.status_code == 202
    job_id = post.json()["job_id"]

    resp = await test_client.get(f"/v1/import/{job_id}", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert "status" in body
