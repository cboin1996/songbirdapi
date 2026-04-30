import uuid as _uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base, Role, User

_engine = None
_session_factory = None


def init_engine(dsn: str):
    global _engine, _session_factory
    _engine = create_async_engine(
        dsn, echo=False, pool_size=20, max_overflow=10, pool_pre_ping=True
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
            hashed_password=hash_password(password),
            role=Role.admin,
        )
        session.add(user)
        await session.commit()


async def dispose_engine():
    await _engine.dispose()


async def get_db():
    # SQLAlchemy 2.0 async autobegins a transaction on the first query. On
    # read-only routes (and on routes that error before a commit) nothing
    # commits or rolls back, so the underlying asyncpg connection returns
    # to the pool 'idle in transaction'. Roll back on exit to release it.
    async with _session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.rollback()
