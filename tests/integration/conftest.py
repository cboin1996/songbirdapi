import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from songbirdapi import crud
from songbirdapi.database import get_db
from songbirdapi.models import Base, Role, User
from songbirdapi.security import hash_password
from songbirdapi.server import app
from songbirdapi.settings import SongbirdServerConfig

if os.getenv("ENV") not in ("dev", "test"):
    pytest.skip("integration tests require ENV=dev or ENV=test", allow_module_level=True)

# One engine created at import time (sync, no event loop required).
# Overriding get_db means both fixtures and app routes share this engine/pool.
_config = SongbirdServerConfig()  # pyright: ignore
_engine = create_async_engine(_config.postgres_dsn)
_TestingSession = async_sessionmaker(_engine, expire_on_commit=False)


async def _override_get_db():
    async with _TestingSession() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture(scope="session")
async def test_client():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await _engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def admin_user(test_client):
    async with _TestingSession() as db:
        user = User(
            id=str(uuid.uuid4()),
            username=f"testadmin_{uuid.uuid4().hex[:6]}",
            email=f"testadmin_{uuid.uuid4().hex[:6]}@test.com",
            hashed_password=hash_password("testpass123"),
            role=Role.admin,
        )
        await crud.create_user(db, user)
    yield user
    async with _TestingSession() as db:
        await crud.delete_user(db, user.id)


@pytest_asyncio.fixture(scope="session")
async def regular_user(test_client):
    async with _TestingSession() as db:
        user = User(
            id=str(uuid.uuid4()),
            username=f"testuser_{uuid.uuid4().hex[:6]}",
            email=f"testuser_{uuid.uuid4().hex[:6]}@test.com",
            hashed_password=hash_password("testpass123"),
            role=Role.user,
        )
        await crud.create_user(db, user)
    yield user
    async with _TestingSession() as db:
        await crud.delete_user(db, user.id)
