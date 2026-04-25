import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Role, Song, SongDownload, SongPlay, User, UserSong


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


# --- users ---

async def get_user(db: AsyncSession, user_id: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User))
    return list(result.scalars().all())


async def create_user(db: AsyncSession, user: User) -> User:
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, user_id: str, role: Optional[Role] = None, is_active: Optional[bool] = None) -> Optional[User]:
    user = await get_user(db, user_id)
    if not user:
        return None
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: str) -> bool:
    result = await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
    return result.rowcount > 0


# --- library ---

async def list_library_with_songs(db: AsyncSession, user_id: str) -> list[dict]:
    result = await db.execute(
        select(Song, UserSong)
        .join(UserSong, Song.uuid == UserSong.song_id)
        .where(UserSong.user_id == user_id)
        .order_by(UserSong.added_at.desc())
    )
    rows = result.all()
    return [
        {
            "uuid": song.uuid,
            "url": song.url,
            "properties": song.properties,
            "added_at": entry.added_at.isoformat(),
            "last_position": entry.last_position,
            "last_played_at": entry.last_played_at.isoformat() if entry.last_played_at else None,
        }
        for song, entry in rows
    ]


async def get_library(db: AsyncSession, user_id: str) -> list[UserSong]:
    result = await db.execute(select(UserSong).where(UserSong.user_id == user_id))
    return list(result.scalars().all())


async def get_library_entry(db: AsyncSession, user_id: str, song_id: str) -> Optional[UserSong]:
    result = await db.execute(
        select(UserSong).where(UserSong.user_id == user_id, UserSong.song_id == song_id)
    )
    return result.scalar_one_or_none()


async def add_to_library(db: AsyncSession, user_id: str, song_id: str) -> UserSong:
    existing = await get_library_entry(db, user_id, song_id)
    if existing:
        return existing
    entry = UserSong(user_id=user_id, song_id=song_id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def remove_from_library(db: AsyncSession, user_id: str, song_id: str) -> bool:
    result = await db.execute(
        delete(UserSong).where(UserSong.user_id == user_id, UserSong.song_id == song_id)
    )
    await db.commit()
    return result.rowcount > 0


# --- plays / downloads ---

def _window_cutoff(window: str) -> datetime | None:
    if window == "day":
        return datetime.now(timezone.utc) - timedelta(days=1)
    if window == "week":
        return datetime.now(timezone.utc) - timedelta(weeks=1)
    return None  # "all"


async def record_play(db: AsyncSession, song_id: str, user_id: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    existing = await db.execute(
        select(SongPlay).where(
            SongPlay.song_id == song_id,
            SongPlay.user_id == user_id,
            SongPlay.played_at >= cutoff,
        )
    )
    if existing.scalar_one_or_none():
        return False
    db.add(SongPlay(id=str(_uuid.uuid4()), song_id=song_id, user_id=user_id))
    await db.commit()
    return True


async def record_download(db: AsyncSession, song_id: str, user_id: str) -> None:
    db.add(SongDownload(id=str(_uuid.uuid4()), song_id=song_id, user_id=user_id))
    await db.commit()


async def get_popular_songs(db: AsyncSession, window: str, limit: int = 10) -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, func.count(SongPlay.id).label("count"))
        .join(SongPlay, Song.uuid == SongPlay.song_id)
        .group_by(Song.uuid)
        .order_by(func.count(SongPlay.id).desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(SongPlay.played_at >= cutoff)
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "count": c} for s, c in result.all()]


async def get_popular_downloads(db: AsyncSession, window: str, limit: int = 10) -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, func.count(SongDownload.id).label("count"))
        .join(SongDownload, Song.uuid == SongDownload.song_id)
        .group_by(Song.uuid)
        .order_by(func.count(SongDownload.id).desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(SongDownload.downloaded_at >= cutoff)
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "count": c} for s, c in result.all()]


async def get_recently_added(db: AsyncSession, limit: int = 10) -> list[Song]:
    result = await db.execute(
        select(Song).where(Song.properties.isnot(None)).order_by(Song.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_most_libraryed(db: AsyncSession, window: str, limit: int = 10) -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, func.count(UserSong.song_id).label("count"))
        .join(UserSong, Song.uuid == UserSong.song_id)
        .group_by(Song.uuid)
        .order_by(func.count(UserSong.song_id).desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(UserSong.added_at >= cutoff)
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "count": c} for s, c in result.all()]


async def get_user_most_played(db: AsyncSession, user_id: str, limit: int = 10) -> list[dict]:
    q = (
        select(Song, func.count(SongPlay.id).label("count"))
        .join(SongPlay, Song.uuid == SongPlay.song_id)
        .where(SongPlay.user_id == user_id)
        .group_by(Song.uuid)
        .order_by(func.count(SongPlay.id).desc())
        .limit(limit)
    )
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "count": c} for s, c in result.all()]


async def get_user_recently_played(db: AsyncSession, user_id: str, limit: int = 10) -> list[dict]:
    result = await db.execute(
        select(Song, UserSong.last_played_at)
        .join(UserSong, Song.uuid == UserSong.song_id)
        .where(UserSong.user_id == user_id, UserSong.last_played_at.isnot(None))
        .order_by(UserSong.last_played_at.desc())
        .limit(limit)
    )
    return [
        {"uuid": s.uuid, "properties": s.properties, "last_played_at": lp.isoformat()}
        for s, lp in result.all()
    ]


async def update_position(db: AsyncSession, user_id: str, song_id: str, position: float) -> Optional[UserSong]:
    entry = await get_library_entry(db, user_id, song_id)
    if not entry:
        return None
    entry.last_position = position
    entry.last_played_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(entry)
    return entry
