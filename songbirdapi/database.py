from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

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


async def dispose_engine():
    await _engine.dispose()


async def get_db():
    async with _session_factory() as session:
        yield session
