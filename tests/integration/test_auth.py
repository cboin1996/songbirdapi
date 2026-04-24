import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_root_is_public(test_client: AsyncClient):
    assert (await test_client.get("/")).status_code == 200


async def test_protected_route_requires_auth(test_client: AsyncClient):
    assert (await test_client.get("/properties/nonexistent-id")).status_code == 401


async def test_login_success(test_client: AsyncClient, admin_user):
    resp = await test_client.post("/auth/login", json={"username": admin_user.username, "password": "testpass123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == admin_user.username
    assert body["role"] == "admin"
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies


async def test_login_wrong_password(test_client: AsyncClient, admin_user):
    resp = await test_client.post("/auth/login", json={"username": admin_user.username, "password": "wrong"})
    assert resp.status_code == 401


async def test_login_unknown_user(test_client: AsyncClient):
    resp = await test_client.post("/auth/login", json={"username": "nobody", "password": "pass"})
    assert resp.status_code == 401


async def test_me_returns_current_user(test_client: AsyncClient, regular_user):
    login = await test_client.post("/auth/login", json={"username": regular_user.username, "password": "testpass123"})
    resp = await test_client.get("/auth/me", cookies=login.cookies)
    assert resp.status_code == 200
    assert resp.json()["username"] == regular_user.username


async def test_logout_clears_cookies(test_client: AsyncClient, admin_user):
    login = await test_client.post("/auth/login", json={"username": admin_user.username, "password": "testpass123"})
    resp = await test_client.post("/auth/logout", cookies=login.cookies)
    assert resp.status_code == 200
    assert resp.cookies.get("access_token", "") == ""


async def test_register_requires_admin(test_client: AsyncClient, regular_user):
    login = await test_client.post("/auth/login", json={"username": regular_user.username, "password": "testpass123"})
    resp = await test_client.post(
        "/auth/register",
        json={"username": "newuser", "email": "new@test.com", "password": "pass123"},
        cookies=login.cookies,
    )
    assert resp.status_code == 403


async def test_register_as_admin(test_client: AsyncClient, admin_user):
    import uuid
    username = f"newuser_{uuid.uuid4().hex[:6]}"
    login = await test_client.post("/auth/login", json={"username": admin_user.username, "password": "testpass123"})
    resp = await test_client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@test.com", "password": "pass123"},
        cookies=login.cookies,
    )
    assert resp.status_code == 201
    assert resp.json()["username"] == username


async def test_token_refresh(test_client: AsyncClient, regular_user):
    login = await test_client.post("/auth/login", json={"username": regular_user.username, "password": "testpass123"})
    resp = await test_client.post("/auth/refresh", cookies=login.cookies)
    assert resp.status_code == 200
    assert "access_token" in resp.cookies
