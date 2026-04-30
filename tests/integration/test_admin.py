import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        "/v1/auth/login", json={"username": user.username, "password": "testpass123"}
    )
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
    body = resp.json()
    assert "total" in body
    assert "errors" in body
    assert isinstance(body["errors"], list)


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


async def test_list_users_as_regular_user_forbidden(
    test_client: AsyncClient, regular_user
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/admin/users", cookies=cookies)
    assert resp.status_code == 403


async def test_update_user_not_found(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.patch(
        "/v1/admin/users/00000000-0000-0000-0000-000000000000",
        json={"is_active": True},
        cookies=cookies,
    )
    assert resp.status_code == 404


async def test_update_user_role_as_admin(
    test_client: AsyncClient, admin_user, regular_user
):
    cookies = await login(test_client, admin_user)
    resp = await test_client.patch(
        f"/v1/admin/users/{regular_user.id}",
        json={"role": "user"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


async def test_delete_user_as_admin(test_client: AsyncClient, admin_user):
    import uuid

    admin_login = await test_client.post(
        "/v1/auth/login",
        json={"username": admin_user.username, "password": "testpass123"},
    )
    uname = f"todelete_{uuid.uuid4().hex[:6]}"
    reg = await test_client.post(
        "/v1/auth/register",
        json={"username": uname, "email": f"{uname}@test.com", "password": "pass123"},
        cookies=admin_login.cookies,
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]

    cookies = await login(test_client, admin_user)
    resp = await test_client.delete(f"/v1/admin/users/{user_id}", cookies=cookies)
    assert resp.status_code == 204


async def test_delete_user_not_found(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.delete(
        "/v1/admin/users/00000000-0000-0000-0000-000000000000", cookies=cookies
    )
    assert resp.status_code == 404


async def test_delete_user_requires_admin(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.delete("/v1/admin/users/some-id", cookies=cookies)
    assert resp.status_code == 403


async def test_get_edit_jobs_as_admin(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get("/v1/admin/edit-jobs", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "jobs" in body
    assert isinstance(body["jobs"], list)


async def test_get_edit_jobs_requires_admin(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get("/v1/admin/edit-jobs", cookies=cookies)
    assert resp.status_code == 403


async def test_get_edit_jobs_requires_auth(test_client: AsyncClient):
    resp = await test_client.get("/v1/admin/edit-jobs")
    assert resp.status_code == 401


async def test_stats_requires_auth(test_client: AsyncClient):
    resp = await test_client.get("/v1/admin/stats")
    assert resp.status_code == 401


async def test_stats_has_extended_fields(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get("/v1/admin/stats", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "plays_by_day" in body
    assert "top_songs" in body
    assert "per_user" in body
    assert "disk_total" in body
    assert "disk_free" in body
