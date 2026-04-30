import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        "/v1/auth/login", json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


async def test_create_share_link(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post(
        f"/v1/share/songs/{sample_song.uuid}", cookies=cookies
    )
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert "token" in body


async def test_share_info_no_auth(test_client: AsyncClient, regular_user, sample_song):
    cookies = await login(test_client, regular_user)
    create_resp = await test_client.post(
        f"/v1/share/songs/{sample_song.uuid}", cookies=cookies
    )
    token = create_resp.json()["token"]

    resp = await test_client.get(f"/v1/share/{token}/info")
    assert resp.status_code == 200
    body = resp.json()
    assert "song_id" in body
    assert "token" in body


async def test_create_share_link_nonexistent_song(
    test_client: AsyncClient, regular_user
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.post("/v1/share/songs/nonexistent", cookies=cookies)
    assert resp.status_code == 404


async def test_share_info_bad_token(test_client: AsyncClient):
    resp = await test_client.get("/v1/share/badtoken/info")
    assert resp.status_code == 404


async def test_create_share_requires_auth(test_client: AsyncClient, sample_song):
    resp = await test_client.post(f"/v1/share/songs/{sample_song.uuid}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /{token}/download
# ---------------------------------------------------------------------------


async def test_download_shared_bad_token(test_client: AsyncClient):
    resp = await test_client.get("/v1/share/badtoken/download")
    assert resp.status_code == 404


async def test_download_shared_no_file(
    test_client: AsyncClient, regular_user, sample_song
):
    # sample_song.file_path is /tmp/test-song.mp3 which doesn't actually exist on disk
    cookies = await login(test_client, regular_user)
    create_resp = await test_client.post(
        f"/v1/share/songs/{sample_song.uuid}", cookies=cookies
    )
    assert create_resp.status_code in (200, 201)
    token = create_resp.json()["token"]

    resp = await test_client.get(f"/v1/share/{token}/download")
    # file doesn't exist on disk — expect 404
    assert resp.status_code == 404
