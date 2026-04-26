import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post("/v1/auth/login", json={"username": user.username, "password": "testpass123"})
    return dict(resp.cookies)


async def test_stats_as_admin(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get("/v1/admin/stats", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "song_count" in body
    assert "user_count" in body
    assert "disk_bytes" in body
    assert "recent_jobs" in body


async def test_stats_as_regular_user_forbidden(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/admin/stats", cookies=cookies)
    assert resp.status_code == 403


async def test_errors_as_admin(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get("/v1/admin/errors", cookies=cookies)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_errors_as_regular_user_forbidden(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/admin/errors", cookies=cookies)
    assert resp.status_code == 403


async def test_update_user_as_admin(test_client: AsyncClient, admin_user, regular_user):
    cookies = await login(test_client, admin_user)

    resp = await test_client.patch(
        f"/v1/admin/users/{regular_user.id}",
        json={"is_active": False},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    restore = await test_client.patch(
        f"/v1/admin/users/{regular_user.id}",
        json={"is_active": True},
        cookies=cookies,
    )
    assert restore.status_code == 200
    assert restore.json()["is_active"] is True


async def test_list_users_as_admin(test_client: AsyncClient, admin_user, regular_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get("/v1/admin/users", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 2


async def test_list_users_as_regular_user_forbidden(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/admin/users", cookies=cookies)
    assert resp.status_code == 403
