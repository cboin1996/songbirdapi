import uuid

import pytest
from httpx import AsyncClient
from songbirdapi.routes import (
    ADMIN_EDIT_JOBS,
    ADMIN_ERRORS,
    ADMIN_IMPORTS,
    ADMIN_STATS,
    ADMIN_USERS,
    AUTH_LOGIN,
    AUTH_REGISTER,
    IMPORT,
    admin_user_path,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

MINIMAL_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 413


async def login(test_client: AsyncClient, user) -> dict:
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": user.username, "password": "testpass123"}
    )
    return dict(resp.cookies)


# ── Stats ──


async def test_stats_as_admin(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(ADMIN_STATS, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "song_count" in body
    assert "user_count" in body
    assert "disk_bytes" in body
    assert "recent_jobs" in body


async def test_stats_as_regular_user_forbidden(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(ADMIN_STATS, cookies=cookies)
    assert resp.status_code == 403


async def test_stats_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(ADMIN_STATS)
    assert resp.status_code == 401


async def test_stats_has_extended_fields(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(ADMIN_STATS, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "plays_by_day" in body
    assert "top_songs" in body
    assert "per_user" in body
    assert "disk_total" in body
    assert "disk_free" in body
    assert "edit_job_count" in body
    assert "error_log_count" in body


# ── Errors ──


async def test_errors_as_admin(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(ADMIN_ERRORS, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "errors" in body
    assert isinstance(body["errors"], list)
    assert "source_counts" in body
    assert isinstance(body["source_counts"], dict)


async def test_errors_as_regular_user_forbidden(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(ADMIN_ERRORS, cookies=cookies)
    assert resp.status_code == 403


async def test_errors_search(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(
        f"{ADMIN_ERRORS}?query=nonexistent_xyz_12345", cookies=cookies
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["errors"] == []


# ── Users ──


async def test_list_users_as_admin(test_client: AsyncClient, admin_user, regular_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(ADMIN_USERS, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "users" in body
    assert isinstance(body["users"], list)
    assert body["total"] >= 2


async def test_list_users_as_regular_user_forbidden(
    test_client: AsyncClient, regular_user
):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(ADMIN_USERS, cookies=cookies)
    assert resp.status_code == 403


async def test_list_users_pagination(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(f"{ADMIN_USERS}?limit=1&offset=0", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["users"]) <= 1
    assert body["total"] >= 1


async def test_list_users_search(test_client: AsyncClient, admin_user, regular_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(
        f"{ADMIN_USERS}?query={regular_user.username}", cookies=cookies
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(u["username"] == regular_user.username for u in body["users"])


async def test_list_users_search_no_results(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(
        f"{ADMIN_USERS}?query=nonexistent_user_xyz_999", cookies=cookies
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["users"] == []


async def test_list_users_search_by_role(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(f"{ADMIN_USERS}?query=admin", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert all(u["role"] == "admin" for u in body["users"])


async def test_update_user_as_admin(test_client: AsyncClient, admin_user, regular_user):
    cookies = await login(test_client, admin_user)

    resp = await test_client.patch(
        admin_user_path(regular_user.id),
        json={"is_active": False},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    restore = await test_client.patch(
        admin_user_path(regular_user.id),
        json={"is_active": True},
        cookies=cookies,
    )
    assert restore.status_code == 200
    assert restore.json()["is_active"] is True


async def test_update_user_not_found(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.patch(
        admin_user_path("00000000-0000-0000-0000-000000000000"),
        json={"is_active": True},
        cookies=cookies,
    )
    assert resp.status_code == 404


async def test_update_user_role_as_admin(
    test_client: AsyncClient, admin_user, regular_user
):
    cookies = await login(test_client, admin_user)
    resp = await test_client.patch(
        admin_user_path(regular_user.id),
        json={"role": "user"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


async def test_delete_user_requires_password(test_client: AsyncClient, admin_user):
    admin_login = await test_client.post(
        AUTH_LOGIN,
        json={"username": admin_user.username, "password": "testpass123"},
    )
    uname = f"todelete_{uuid.uuid4().hex[:6]}"
    reg = await test_client.post(
        AUTH_REGISTER,
        json={"username": uname, "email": f"{uname}@test.com", "password": "pass123"},
        cookies=admin_login.cookies,
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]

    cookies = await login(test_client, admin_user)
    resp = await test_client.request(
        "DELETE",
        admin_user_path(user_id),
        json={"password": "testpass123"},
        cookies=cookies,
    )
    assert resp.status_code == 204


async def test_delete_user_wrong_password(test_client: AsyncClient, admin_user):
    admin_login = await test_client.post(
        AUTH_LOGIN,
        json={"username": admin_user.username, "password": "testpass123"},
    )
    uname = f"todelete_{uuid.uuid4().hex[:6]}"
    reg = await test_client.post(
        AUTH_REGISTER,
        json={"username": uname, "email": f"{uname}@test.com", "password": "pass123"},
        cookies=admin_login.cookies,
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]

    cookies = await login(test_client, admin_user)
    resp = await test_client.request(
        "DELETE",
        admin_user_path(user_id),
        json={"password": "wrongpassword"},
        cookies=cookies,
    )
    assert resp.status_code == 401


async def test_delete_user_not_found(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.request(
        "DELETE",
        admin_user_path("00000000-0000-0000-0000-000000000000"),
        json={"password": "testpass123"},
        cookies=cookies,
    )
    assert resp.status_code == 404


async def test_delete_user_requires_admin(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.request(
        "DELETE",
        admin_user_path("some-id"),
        json={"password": "testpass123"},
        cookies=cookies,
    )
    assert resp.status_code == 403


# ── Edit Jobs ──


async def test_get_edit_jobs_as_admin(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(ADMIN_EDIT_JOBS, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "jobs" in body
    assert isinstance(body["jobs"], list)
    assert "status_counts" in body
    assert isinstance(body["status_counts"], dict)


async def test_get_edit_jobs_requires_admin(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(ADMIN_EDIT_JOBS, cookies=cookies)
    assert resp.status_code == 403


async def test_get_edit_jobs_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(ADMIN_EDIT_JOBS)
    assert resp.status_code == 401


async def test_get_edit_jobs_search(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(
        f"{ADMIN_EDIT_JOBS}?query=nonexistent_xyz", cookies=cookies
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["jobs"] == []


async def test_get_edit_jobs_pagination(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(f"{ADMIN_EDIT_JOBS}?limit=1&offset=0", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["jobs"]) <= 1


# ── Admin Imports ──


async def test_admin_imports_as_admin(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(ADMIN_IMPORTS, cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "jobs" in body
    assert isinstance(body["jobs"], list)
    assert "status_counts" in body
    assert isinstance(body["status_counts"], dict)


async def test_admin_imports_requires_admin(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(ADMIN_IMPORTS, cookies=cookies)
    assert resp.status_code == 403


async def test_admin_imports_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(ADMIN_IMPORTS)
    assert resp.status_code == 401


async def test_admin_imports_shows_all_users(
    test_client: AsyncClient, admin_user, regular_user
):
    reg_cookies = await login(test_client, regular_user)
    post = await test_client.post(
        IMPORT,
        files={"file": ("admin-test.mp3", MINIMAL_MP3, "audio/mpeg")},
        cookies=reg_cookies,
    )
    assert post.status_code == 202

    adm_cookies = await login(test_client, admin_user)
    resp = await test_client.get(ADMIN_IMPORTS, cookies=adm_cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(j["username"] == regular_user.username for j in body["jobs"])


async def test_admin_imports_search(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(
        f"{ADMIN_IMPORTS}?query=nonexistent_file_xyz", cookies=cookies
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["jobs"] == []


async def test_admin_imports_pagination(test_client: AsyncClient, admin_user):
    cookies = await login(test_client, admin_user)
    resp = await test_client.get(f"{ADMIN_IMPORTS}?limit=1&offset=0", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["jobs"]) <= 1


# ── User Imports (search) ──


async def test_user_imports_search(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    resp = await test_client.get(f"{IMPORT}?query=nonexistent_xyz_999", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["jobs"] == []


async def test_user_imports_search_by_status(test_client: AsyncClient, regular_user):
    cookies = await login(test_client, regular_user)
    await test_client.post(
        IMPORT,
        files={"file": ("search-test.mp3", MINIMAL_MP3, "audio/mpeg")},
        cookies=cookies,
    )
    resp = await test_client.get(f"{IMPORT}?query=pending", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert all(j["status"] == "pending" for j in body["jobs"])
