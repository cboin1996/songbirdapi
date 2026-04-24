import uuid as _uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base, Role, User

_engine = None
_session_factory = None


def init_engine(dsn: str):
    global _engine, _session_factory
    _engine = create_async_engine(dsn, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def create_schema():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_songs_fts ON songs USING GIN (
                to_tsvector('english',
                    coalesce(properties->>'trackName', '') || ' ' ||
                    coalesce(properties->>'artistName', '') || ' ' ||
                    coalesce(properties->>'collectionName', '')
                )
            )
        """))


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
    async with _session_factory() as session:
        yield session
