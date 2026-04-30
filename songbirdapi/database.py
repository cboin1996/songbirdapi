import uuid as _uuid
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base, Role, User

_engine = None
_session_factory = None


def init_engine(dsn: str):
    global _engine, _session_factory
    # Pool defenses (carefully chosen to avoid the "cannot switch to state 15"
    # race that bit us when all three were on AND pool_pre_ping was issuing
    # SELECT 1 mid-recycle):
    #
    # - pool_pre_ping is OFF — it was the racer.
    # - pool_recycle=600 — sqlalchemy itself ages out connections every 10 min.
    #   Catches sessions that leaked because FastAPI didn't advance our
    #   dependency generator on client disconnect (browser closes mid-request).
    # - idle_in_transaction_session_timeout=120s on the pg side — pg terminates
    #   any backend stuck "idle in transaction" longer than that, so leaks
    #   self-heal even if sqlalchemy doesn't notice.
    _engine = create_async_engine(
        dsn,
        echo=False,
        pool_size=20,
        max_overflow=10,
        pool_recycle=600,
        connect_args={
            "server_settings": {"idle_in_transaction_session_timeout": "120000"},
        },
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def create_schema():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed_admin(username: str, email: str, password: str):
    from .crud import get_user_by_username
    from .security import hash_password

    if not username or not email or not password:
        return
    async with _session_factory() as session:
        existing = await get_user_by_username(session, username)
        if existing:
            return
        user = User(
            id=str(_uuid.uuid4()),
            username=username,
            email=email,
            hashed_password=await hash_password(password),
            role=Role.admin,
        )
        session.add(user)
        await session.commit()


async def dispose_engine():
    await _engine.dispose()


@asynccontextmanager
async def session_scope():
    # SQLAlchemy 2.0 async autobegins a transaction on the first query. On
    # read-only paths (and on paths that error before a commit) nothing
    # commits or rolls back, so the underlying asyncpg connection returns
    # to the pool 'idle in transaction'. Roll back in finally to release.
    # No-op when a commit has already cleared the transaction.
    async with _session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


async def get_db():
    async with session_scope() as session:
        yield session
