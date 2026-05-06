import pytest
from httpx import AsyncClient
from songbirdapi.routes import (
    AUTH_LOGIN,
    AUTH_LOGOUT,
    AUTH_ME,
    AUTH_PASSWORD,
    AUTH_REFRESH,
    AUTH_REGISTER,
    admin_user_path,
    properties_path,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_root_is_public(test_client: AsyncClient):
    assert (await test_client.get("/")).status_code == 200


async def test_protected_route_requires_auth(test_client: AsyncClient):
    assert (await test_client.get(properties_path("nonexistent-id"))).status_code == 401


async def test_login_success(test_client: AsyncClient, admin_user):
    resp = await test_client.post(
        AUTH_LOGIN,
        json={"username": admin_user.username, "password": "testpass123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == admin_user.username
    assert body["role"] == "admin"
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies


async def test_login_wrong_password(test_client: AsyncClient, admin_user):
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": admin_user.username, "password": "wrong"}
    )
    assert resp.status_code == 401


async def test_login_unknown_user(test_client: AsyncClient):
    resp = await test_client.post(
        AUTH_LOGIN, json={"username": "nobody", "password": "pass"}
    )
    assert resp.status_code == 401


async def test_me_returns_current_user(test_client: AsyncClient, regular_user):
    login = await test_client.post(
        AUTH_LOGIN,
        json={"username": regular_user.username, "password": "testpass123"},
    )
    resp = await test_client.get(AUTH_ME, cookies=login.cookies)
    assert resp.status_code == 200
    assert resp.json()["username"] == regular_user.username


async def test_logout_clears_cookies(test_client: AsyncClient, admin_user):
    login = await test_client.post(
        AUTH_LOGIN,
        json={"username": admin_user.username, "password": "testpass123"},
    )
    resp = await test_client.post(AUTH_LOGOUT, cookies=login.cookies)
    assert resp.status_code == 200
    assert resp.cookies.get("access_token", "") == ""


async def test_register_requires_admin(test_client: AsyncClient, regular_user):
    login = await test_client.post(
        AUTH_LOGIN,
        json={"username": regular_user.username, "password": "testpass123"},
    )
    resp = await test_client.post(
        AUTH_REGISTER,
        json={"username": "newuser", "email": "new@test.com", "password": "pass123"},
        cookies=login.cookies,
    )
    assert resp.status_code == 403


async def test_register_as_admin(test_client: AsyncClient, admin_user):
    import uuid

    username = f"newuser_{uuid.uuid4().hex[:6]}"
    login = await test_client.post(
        AUTH_LOGIN,
        json={"username": admin_user.username, "password": "testpass123"},
    )
    resp = await test_client.post(
        AUTH_REGISTER,
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "pass123",
        },
        cookies=login.cookies,
    )
    assert resp.status_code == 201
    assert resp.json()["username"] == username


async def test_token_refresh(test_client: AsyncClient, regular_user):
    login = await test_client.post(
        AUTH_LOGIN,
        json={"username": regular_user.username, "password": "testpass123"},
    )
    resp = await test_client.post(AUTH_REFRESH, cookies=login.cookies)
    assert resp.status_code == 200
    assert "access_token" in resp.cookies


async def test_refresh_without_cookie_fails(test_client: AsyncClient):
    resp = await test_client.post(AUTH_REFRESH)
    assert resp.status_code == 401


async def test_me_requires_auth(test_client: AsyncClient):
    resp = await test_client.get(AUTH_ME)
    assert resp.status_code == 401


async def test_register_duplicate_username(test_client: AsyncClient, admin_user):
    import uuid

    login_resp = await test_client.post(
        AUTH_LOGIN,
        json={"username": admin_user.username, "password": "testpass123"},
    )
    # register a new user
    unique = uuid.uuid4().hex[:8]
    await test_client.post(
        AUTH_REGISTER,
        json={"username": unique, "email": f"{unique}@test.com", "password": "pass"},
        cookies=login_resp.cookies,
    )
    # try registering same username again
    resp = await test_client.post(
        AUTH_REGISTER,
        json={
            "username": unique,
            "email": f"other_{unique}@test.com",
            "password": "pass",
        },
        cookies=login_resp.cookies,
    )
    assert resp.status_code == 409


async def test_register_duplicate_email(test_client: AsyncClient, admin_user):
    import uuid

    login_resp = await test_client.post(
        AUTH_LOGIN,
        json={"username": admin_user.username, "password": "testpass123"},
    )
    unique = uuid.uuid4().hex[:8]
    await test_client.post(
        AUTH_REGISTER,
        json={"username": unique, "email": f"{unique}@test.com", "password": "pass"},
        cookies=login_resp.cookies,
    )
    resp = await test_client.post(
        AUTH_REGISTER,
        json={
            "username": f"other_{unique}",
            "email": f"{unique}@test.com",
            "password": "pass",
        },
        cookies=login_resp.cookies,
    )
    assert resp.status_code == 409


async def test_register_without_auth(test_client: AsyncClient):
    resp = await test_client.post(
        AUTH_REGISTER,
        json={"username": "anon", "email": "anon@test.com", "password": "pass"},
    )
    assert resp.status_code == 401


async def test_change_password(test_client: AsyncClient, admin_user):
    import uuid

    # register a throwaway user to change password on
    admin_login = await test_client.post(
        AUTH_LOGIN,
        json={"username": admin_user.username, "password": "testpass123"},
    )
    uname = f"pwchange_{uuid.uuid4().hex[:6]}"
    await test_client.post(
        AUTH_REGISTER,
        json={"username": uname, "email": f"{uname}@test.com", "password": "oldpass"},
        cookies=admin_login.cookies,
    )
    user_login = await test_client.post(
        AUTH_LOGIN, json={"username": uname, "password": "oldpass"}
    )
    assert user_login.status_code == 200

    resp = await test_client.patch(
        AUTH_PASSWORD,
        json={"current_password": "oldpass", "new_password": "newpass"},
        cookies=user_login.cookies,
    )
    assert resp.status_code == 204

    # old password should no longer work
    old_login = await test_client.post(
        AUTH_LOGIN, json={"username": uname, "password": "oldpass"}
    )
    assert old_login.status_code == 401

    # new password should work
    new_login = await test_client.post(
        AUTH_LOGIN, json={"username": uname, "password": "newpass"}
    )
    assert new_login.status_code == 200


async def test_change_password_wrong_current(test_client: AsyncClient, regular_user):
    login_resp = await test_client.post(
        AUTH_LOGIN,
        json={"username": regular_user.username, "password": "testpass123"},
    )
    resp = await test_client.patch(
        AUTH_PASSWORD,
        json={"current_password": "wrongpassword", "new_password": "newpass"},
        cookies=login_resp.cookies,
    )
    assert resp.status_code == 401


async def test_change_password_requires_auth(test_client: AsyncClient):
    resp = await test_client.patch(
        AUTH_PASSWORD,
        json={"current_password": "x", "new_password": "y"},
    )
    assert resp.status_code == 401


async def test_disabled_user_cannot_login(test_client: AsyncClient, admin_user):
    import uuid

    admin_login = await test_client.post(
        AUTH_LOGIN,
        json={"username": admin_user.username, "password": "testpass123"},
    )
    uname = f"disabled_{uuid.uuid4().hex[:6]}"
    reg = await test_client.post(
        AUTH_REGISTER,
        json={"username": uname, "email": f"{uname}@test.com", "password": "pass123"},
        cookies=admin_login.cookies,
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]

    # disable the user
    await test_client.patch(
        admin_user_path(user_id),
        json={"is_active": False},
        cookies=admin_login.cookies,
    )

    resp = await test_client.post(
        AUTH_LOGIN, json={"username": uname, "password": "pass123"}
    )
    assert resp.status_code == 403
