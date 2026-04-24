from typing import Optional

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Song


async def get_song(db: AsyncSession, uuid: str) -> Optional[Song]:
    result = await db.execute(select(Song).where(Song.uuid == uuid))
    return result.scalar_one_or_none()


async def get_songs_by_url(db: AsyncSession, url: str) -> list[Song]:
    result = await db.execute(select(Song).where(Song.url == url))
    return list(result.scalars().all())


async def insert_song(db: AsyncSession, song: Song) -> Song:
    db.add(song)
    await db.commit()
    await db.refresh(song)
    return song


async def update_song_properties(db: AsyncSession, uuid: str, properties: dict) -> Optional[Song]:
    song = await get_song(db, uuid)
    if not song:
        return None
    song.properties = properties
    await db.commit()
    await db.refresh(song)
    return song


async def delete_song(db: AsyncSession, uuid: str) -> bool:
    result = await db.execute(delete(Song).where(Song.uuid == uuid))
    await db.commit()
    return result.rowcount > 0


async def search_songs(db: AsyncSession, query: str) -> list[Song]:
    result = await db.execute(
        select(Song).where(
            func.to_tsvector(
                "english",
                func.coalesce(Song.properties["trackName"].as_string(), "")
                + " "
                + func.coalesce(Song.properties["artistName"].as_string(), "")
                + " "
                + func.coalesce(Song.properties["collectionName"].as_string(), ""),
            ).op("@@")(func.plainto_tsquery("english", query))
        )
    )
    return list(result.scalars().all())


async def list_songs(db: AsyncSession) -> list[Song]:
    result = await db.execute(select(Song))
    return list(result.scalars().all())
