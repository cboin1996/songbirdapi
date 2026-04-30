import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from songbirdapi import crud, database
from songbirdapi.database import get_db
from songbirdapi.models import Base, Role, Song, User
from songbirdapi.security import hash_password
from songbirdapi.server import app
from songbirdapi.settings import SongbirdServerConfig

if os.getenv("ENV") not in ("dev", "test"):
    pytest.skip(
        "integration tests require ENV=dev or ENV=test", allow_module_level=True
    )


def pytest_collection_modifyitems(config, items):
    if os.getenv("CI"):
        skip_local = pytest.mark.skip(
            reason="marked local — skipped in CI (requires yt-dlp / network)"
        )
        for item in items:
            if item.get_closest_marker("local"):
                item.add_marker(skip_local)


# One engine created at import time (sync, no event loop required).
# Overriding get_db means both fixtures and app routes share this engine/pool.
_config = SongbirdServerConfig()  # pyright: ignore
_engine = create_async_engine(_config.postgres_dsn)
_TestingSession = async_sessionmaker(_engine, expire_on_commit=False)

# Initialize the module-level session factory so background tasks (edit/imports)
# and the unhandled-exception handler in server.py can open sessions even though
# the FastAPI lifespan never runs under ASGITransport.
database._engine = _engine
database._session_factory = _TestingSession


async def _override_get_db():
    async with _TestingSession() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture(scope="session")
async def test_client():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await _engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _isolate_cookies(test_client):
    """
    httpx AsyncClient is session-scoped, so cookies set by login() in one test
    leak into the next. Clear the jar before each test so `*_requires_auth`
    tests run anonymously and per-test logins start clean.
    """
    test_client.cookies.clear()
    yield
    test_client.cookies.clear()


@pytest_asyncio.fixture(scope="session")
async def admin_user(test_client):
    async with _TestingSession() as db:
        user = User(
            id=str(uuid.uuid4()),
            username=f"testadmin_{uuid.uuid4().hex[:6]}",
            email=f"testadmin_{uuid.uuid4().hex[:6]}@test.com",
            hashed_password=await hash_password("testpass123"),
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
            hashed_password=await hash_password("testpass123"),
            role=Role.user,
        )
        await crud.create_user(db, user)
    yield user
    async with _TestingSession() as db:
        await crud.delete_user(db, user.id)


@pytest_asyncio.fixture(scope="session")
async def sample_song(test_client):
    async with _TestingSession() as db:
        song = Song(
            uuid=str(uuid.uuid4()),
            url="https://example.com/test-song",
            file_path="/tmp/test-song.mp3",
        )
        await crud.insert_song(db, song)
    yield song
    async with _TestingSession() as db:
        await crud.delete_song(db, song.uuid)
