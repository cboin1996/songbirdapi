import pytest
from httpx import AsyncClient
from songbirdapi.routes import HEALTH, VERSION

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_version_no_auth(test_client: AsyncClient):
    resp = await test_client.get(VERSION)
    assert resp.status_code == 200
    body = resp.json()
    assert "api_version" in body
    assert "core_version" in body


async def test_health_no_auth(test_client: AsyncClient):
    resp = await test_client.get(HEALTH)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
