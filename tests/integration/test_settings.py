import pytest
from httpx import AsyncClient
from songbirdapi.routes import AUTH_LOGIN, SETTINGS

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


async def test_get_settings_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(SETTINGS)
    assert resp.status_code == 401


async def test_get_settings_returns_defaults(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(SETTINGS, cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == {"audio_format": "mp3"}


async def test_update_settings_to_m4a(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        SETTINGS, json={"audio_format": "m4a"}, cookies=cookies
    )
    assert resp.status_code == 200
    assert resp.json() == {"audio_format": "m4a"}

    resp = await test_client.get(SETTINGS, cookies=cookies)
    assert resp.json() == {"audio_format": "m4a"}


async def test_update_settings_back_to_mp3(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    await test_client.put(SETTINGS, json={"audio_format": "m4a"}, cookies=cookies)
    resp = await test_client.put(
        SETTINGS, json={"audio_format": "mp3"}, cookies=cookies
    )
    assert resp.status_code == 200
    assert resp.json() == {"audio_format": "mp3"}


async def test_update_settings_invalid_format(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.put(
        SETTINGS, json={"audio_format": "wav"}, cookies=cookies
    )
    assert resp.status_code == 422


async def test_put_settings_requires_auth(test_client: AsyncClient):
    resp = await test_client.put(SETTINGS, json={"audio_format": "m4a"})
    assert resp.status_code == 401


async def test_settings_per_user(test_client: AsyncClient, regular_user, admin_user):
    cookies_regular = await login(test_client, regular_user)
    cookies_admin = await login(test_client, admin_user)

    await test_client.put(
        SETTINGS, json={"audio_format": "m4a"}, cookies=cookies_regular
    )
    await test_client.put(SETTINGS, json={"audio_format": "mp3"}, cookies=cookies_admin)

    resp = await test_client.get(SETTINGS, cookies=cookies_regular)
    assert resp.json()["audio_format"] == "m4a"

    resp = await test_client.get(SETTINGS, cookies=cookies_admin)
    assert resp.json()["audio_format"] == "mp3"
