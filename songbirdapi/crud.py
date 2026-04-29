import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EditJob, EditJobStatus, ImportJob, Playlist, PlaylistSong, RepeatMode, Role, Song, SongDownload, SongEditDraft, SongPlay, SongShareToken, User, UserOfflineSong, UserPlayerState, UserSong


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


async def update_song_artwork(db: AsyncSession, uuid: str, thumb_path: str | None, full_path: str | None) -> Optional[Song]:
    song = await get_song(db, uuid)
    if not song:
        return None
    if thumb_path is not None:
        song.artwork_thumb = thumb_path
    if full_path is not None:
        song.artwork_full = full_path
    await db.commit()
    return song


async def update_song_properties(db: AsyncSession, uuid: str, properties: dict) -> Optional[Song]:
    song = await get_song(db, uuid)
    if not song:
        return None
    song.properties = properties
    await db.commit()
    await db.refresh(song)
    return song


_PUBLISH_REQUIRED = ["trackName", "artistName", "collectionName", "primaryGenreName",
                     "releaseDate", "trackNumber"]


def _get_missing_fields(properties: dict | None, artwork_cached: bool = False) -> list[str]:
    if not properties:
        missing = list(_PUBLISH_REQUIRED)
        if not artwork_cached:
            missing.append("artwork")
        return missing
    missing = [f for f in _PUBLISH_REQUIRED if not bool(properties.get(f))]
    if not artwork_cached and not bool(properties.get("artworkUrl100")):
        missing.append("artwork")
    return missing


def _is_publish_eligible(properties: dict | None, artwork_cached: bool = False) -> bool:
    return len(_get_missing_fields(properties, artwork_cached=artwork_cached)) == 0


async def publish_song(db: AsyncSession, song_id: str, as_original: bool = False) -> None:
    song = await get_song(db, song_id)
    if song:
        song.owner_id = None
        song.source = None if as_original else "community"
        await db.commit()


def _owner_filter(user_id: str | None):
    from sqlalchemy import or_
    if user_id:
        return or_(Song.owner_id.is_(None), Song.owner_id == user_id)
    return Song.owner_id.is_(None)


async def search_songs(db: AsyncSession, query: str, user_id: str | None = None, limit: int = 50) -> list[Song]:
    result = await db.execute(
        select(Song).where(
            _owner_filter(user_id),
            Song.parent_song_id.is_(None),
            func.to_tsvector(
                "english",
                func.coalesce(Song.properties["trackName"].as_string(), "")
                + " "
                + func.coalesce(Song.properties["artistName"].as_string(), "")
                + " "
                + func.coalesce(Song.properties["collectionName"].as_string(), ""),
            ).op("@@")(func.plainto_tsquery("english", query))
        ).limit(limit)
    )
    return list(result.scalars().all())


async def list_songs(db: AsyncSession, user_id: str | None = None) -> list[Song]:
    result = await db.execute(select(Song).where(_owner_filter(user_id)))
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
            "artwork_cached": song.artwork_thumb is not None,
            "parent_song_id": song.parent_song_id,
            "root_song_id": song.root_song_id,
            "owner_id": song.owner_id,
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


async def bulk_remove_from_library(db: AsyncSession, user_id: str, song_ids: list[str]) -> None:
    await db.execute(
        delete(UserSong).where(UserSong.user_id == user_id, UserSong.song_id.in_(song_ids))
    )
    await db.commit()


async def library_ref_count(db: AsyncSession, song_id: str) -> int:
    result = await db.execute(select(func.count()).where(UserSong.song_id == song_id))
    return result.scalar_one()


async def child_ref_count(db: AsyncSession, song_id: str) -> int:
    result = await db.execute(select(func.count()).where(Song.parent_song_id == song_id))
    return result.scalar_one()


async def delete_song(db: AsyncSession, song_id: str) -> None:
    import os
    song = await get_song(db, song_id)
    if not song:
        return
    await db.execute(delete(Song).where(Song.uuid == song_id))
    await db.commit()
    if song.file_path and os.path.exists(song.file_path):
        try:
            os.remove(song.file_path)
        except OSError:
            pass


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


async def get_popular_songs(db: AsyncSession, window: str, limit: int = 10, user_id: str | None = None) -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, func.count(SongPlay.id).label("count"))
        .join(SongPlay, Song.uuid == SongPlay.song_id)
        .where(_owner_filter(user_id))
        .group_by(Song.uuid)
        .order_by(func.count(SongPlay.id).desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(SongPlay.played_at >= cutoff)
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "count": c, "source": s.source, "artwork_cached": s.artwork_thumb is not None} for s, c in result.all()]


async def get_popular_downloads(db: AsyncSession, window: str, limit: int = 10, user_id: str | None = None) -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, func.count(SongDownload.id).label("count"))
        .join(SongDownload, Song.uuid == SongDownload.song_id)
        .where(_owner_filter(user_id))
        .group_by(Song.uuid)
        .order_by(func.count(SongDownload.id).desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(SongDownload.downloaded_at >= cutoff)
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "count": c, "source": s.source, "artwork_cached": s.artwork_thumb is not None} for s, c in result.all()]


async def get_recently_added(db: AsyncSession, limit: int = 50, user_id: str | None = None, window: str = "all") -> list[Song]:
    cutoff = _window_cutoff(window)
    q = select(Song).where(Song.properties.isnot(None), _owner_filter(user_id)).order_by(Song.created_at.desc()).limit(limit)
    if cutoff:
        q = q.where(Song.created_at >= cutoff)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_most_libraryed(db: AsyncSession, window: str, limit: int = 10, user_id: str | None = None) -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, func.count(UserSong.song_id).label("count"))
        .join(UserSong, Song.uuid == UserSong.song_id)
        .where(_owner_filter(user_id))
        .group_by(Song.uuid)
        .order_by(func.count(UserSong.song_id).desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(UserSong.added_at >= cutoff)
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "count": c, "source": s.source, "artwork_cached": s.artwork_thumb is not None} for s, c in result.all()]


async def get_user_most_played(db: AsyncSession, user_id: str, window: str = "all", limit: int = 10) -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, func.count(SongPlay.id).label("count"))
        .join(SongPlay, Song.uuid == SongPlay.song_id)
        .where(SongPlay.user_id == user_id)
        .group_by(Song.uuid)
        .order_by(func.count(SongPlay.id).desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(SongPlay.played_at >= cutoff)
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "count": c, "source": s.source, "artwork_cached": s.artwork_thumb is not None} for s, c in result.all()]


async def get_user_recently_played(db: AsyncSession, user_id: str, limit: int = 50, window: str = "all") -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, UserSong.last_played_at)
        .join(UserSong, Song.uuid == UserSong.song_id)
        .where(UserSong.user_id == user_id, UserSong.last_played_at.isnot(None))
        .order_by(UserSong.last_played_at.desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(UserSong.last_played_at >= cutoff)
    result = await db.execute(q)
    return [
        {"uuid": s.uuid, "properties": s.properties, "last_played_at": lp.isoformat(), "artwork_cached": s.artwork_thumb is not None}
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


async def get_community_recent(db: AsyncSession, limit: int = 10) -> list[Song]:
    result = await db.execute(
        select(Song).where(Song.source == "community", Song.properties.isnot(None)).order_by(Song.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_community_popular(db: AsyncSession, window: str, limit: int = 10) -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, func.count(SongPlay.id).label("count"))
        .join(SongPlay, Song.uuid == SongPlay.song_id)
        .where(Song.source == "community")
        .group_by(Song.uuid)
        .order_by(func.count(SongPlay.id).desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(SongPlay.played_at >= cutoff)
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "count": c, "source": s.source, "artwork_cached": s.artwork_thumb is not None} for s, c in result.all()]


async def get_user_recently_saved(db: AsyncSession, user_id: str, window: str = "all", limit: int = 10) -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, UserSong.added_at)
        .join(UserSong, Song.uuid == UserSong.song_id)
        .where(UserSong.user_id == user_id)
        .order_by(UserSong.added_at.desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(UserSong.added_at >= cutoff)
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "added_at": at.isoformat(), "artwork_cached": s.artwork_thumb is not None} for s, at in result.all()]


async def get_user_most_downloaded(db: AsyncSession, user_id: str, window: str = "all", limit: int = 10) -> list[dict]:
    cutoff = _window_cutoff(window)
    q = (
        select(Song, func.count(SongDownload.id).label("count"))
        .join(SongDownload, Song.uuid == SongDownload.song_id)
        .where(SongDownload.user_id == user_id)
        .group_by(Song.uuid)
        .order_by(func.count(SongDownload.id).desc())
        .limit(limit)
    )
    if cutoff:
        q = q.where(SongDownload.downloaded_at >= cutoff)
    result = await db.execute(q)
    return [{"uuid": s.uuid, "properties": s.properties, "count": c, "source": s.source, "artwork_cached": s.artwork_thumb is not None} for s, c in result.all()]


# --- edit jobs ---

async def create_edit_job(db: AsyncSession, source_song_id: str, user_id: str, params: dict) -> EditJob:
    job = EditJob(id=str(_uuid.uuid4()), source_song_id=source_song_id, user_id=user_id, params=params)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_edit_job(db: AsyncSession, job_id: str) -> Optional[EditJob]:
    result = await db.execute(select(EditJob).where(EditJob.id == job_id))
    return result.scalar_one_or_none()


async def update_edit_job(
    db: AsyncSession,
    job_id: str,
    status: EditJobStatus,
    result_song_id: str | None = None,
    error: str | None = None,
) -> None:
    job = await get_edit_job(db, job_id)
    if not job:
        return
    job.status = status
    job.updated_at = datetime.now(timezone.utc)
    if result_song_id is not None:
        job.result_song_id = result_song_id
    if error is not None:
        job.error = error
    await db.commit()


# --- import jobs ---

async def create_import_job(db: AsyncSession, user_id: str, filename: str) -> ImportJob:
    job = ImportJob(id=str(_uuid.uuid4()), user_id=user_id, filename=filename)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_import_job(db: AsyncSession, job_id: str) -> Optional[ImportJob]:
    result = await db.execute(select(ImportJob).where(ImportJob.id == job_id))
    return result.scalar_one_or_none()


async def list_import_jobs(db: AsyncSession, user_id: str, limit: int = 20, offset: int = 0) -> list[ImportJob]:
    result = await db.execute(
        select(ImportJob)
        .where(ImportJob.user_id == user_id)
        .order_by(ImportJob.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def find_song_by_track_artist(db: AsyncSession, track_name: str, artist_name: str) -> Optional[Song]:
    result = await db.execute(
        select(Song).where(
            Song.properties["trackName"].astext == track_name,
            Song.properties["artistName"].astext == artist_name,
        )
    )
    return result.scalars().first()


async def update_import_job(
    db: AsyncSession,
    job_id: str,
    status: EditJobStatus,
    song_id: str | None = None,
    error: str | None = None,
    duplicate_of: str | None = None,
) -> None:
    job = await get_import_job(db, job_id)
    if not job:
        return
    job.status = status
    job.updated_at = datetime.now(timezone.utc)
    if song_id is not None:
        job.song_id = song_id
    if error is not None:
        job.error = error
    if duplicate_of is not None:
        job.duplicate_of = duplicate_of
    await db.commit()


# --- edit drafts ---

async def get_edit_draft(db: AsyncSession, user_id: str, song_id: str) -> Optional[SongEditDraft]:
    result = await db.execute(
        select(SongEditDraft).where(SongEditDraft.user_id == user_id, SongEditDraft.song_id == song_id)
    )
    return result.scalar_one_or_none()


async def upsert_edit_draft(db: AsyncSession, user_id: str, song_id: str, params: dict) -> SongEditDraft:
    draft = await get_edit_draft(db, user_id, song_id)
    if draft is None:
        draft = SongEditDraft(user_id=user_id, song_id=song_id, params=params)
        db.add(draft)
    else:
        draft.params = params
        draft.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return draft


async def delete_edit_draft(db: AsyncSession, user_id: str, song_id: str) -> bool:
    result = await db.execute(
        delete(SongEditDraft).where(SongEditDraft.user_id == user_id, SongEditDraft.song_id == song_id)
    )
    await db.commit()
    return result.rowcount > 0


async def list_user_drafts(db: AsyncSession, user_id: str) -> list[dict]:
    result = await db.execute(
        select(SongEditDraft, Song)
        .join(Song, SongEditDraft.song_id == Song.uuid)
        .where(SongEditDraft.user_id == user_id)
        .order_by(SongEditDraft.updated_at.desc())
    )
    return [
        {
            "song_id": draft.song_id,
            "properties": song.properties,
            "artwork_cached": song.artwork_thumb is not None,
            "updated_at": draft.updated_at.isoformat(),
        }
        for draft, song in result.all()
    ]


# --- share tokens ---

async def create_share_token(db: AsyncSession, song_id: str, user_id: str, ttl_days: int = 7) -> SongShareToken:
    token = str(_uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    entry = SongShareToken(token=token, song_id=song_id, created_by=user_id, expires_at=expires_at)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def get_share_token(db: AsyncSession, token: str) -> Optional[SongShareToken]:
    result = await db.execute(select(SongShareToken).where(SongShareToken.token == token))
    return result.scalar_one_or_none()


# --- player state ---

async def get_player_state(db: AsyncSession, user_id: str) -> Optional[UserPlayerState]:
    result = await db.execute(select(UserPlayerState).where(UserPlayerState.user_id == user_id))
    return result.scalar_one_or_none()


async def upsert_player_state(
    db: AsyncSession,
    user_id: str,
    shuffle: bool,
    repeat: RepeatMode,
    queue: list[str],
    queue_index: int,
    shuffle_order: list[int] | None = None,
    play_context: str | None = None,
    shuffle_seed: int | None = None,
    shuffle_position: int = 0,
    manual_next: list[str] | None = None,
    current_song_uuid: str | None = None,
) -> UserPlayerState:
    state = await get_player_state(db, user_id)
    if state is None:
        state = UserPlayerState(user_id=user_id)
        db.add(state)
    state.shuffle = shuffle
    state.repeat = repeat
    state.queue = queue
    state.queue_index = queue_index
    state.shuffle_order = shuffle_order
    state.play_context = play_context
    state.shuffle_seed = shuffle_seed
    state.shuffle_position = shuffle_position
    state.manual_next = manual_next or []
    state.current_song_uuid = current_song_uuid
    state.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(state)
    return state


# --- Playlists ---

async def create_playlist(db: AsyncSession, user_id: str, name: str, icon: Optional[str] = None) -> Playlist:
    pl = Playlist(id=str(_uuid.uuid4()), user_id=user_id, name=name, icon=icon)
    db.add(pl)
    await db.commit()
    await db.refresh(pl)
    return pl


async def get_playlist(db: AsyncSession, playlist_id: str) -> Optional[Playlist]:
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
    return result.scalar_one_or_none()


async def list_playlists(db: AsyncSession, user_id: str) -> list[Playlist]:
    result = await db.execute(
        select(Playlist).where(Playlist.user_id == user_id).order_by(Playlist.created_at.asc())
    )
    return list(result.scalars().all())


async def rename_playlist(db: AsyncSession, playlist_id: str, name: str, icon: Optional[str] = None) -> Optional[Playlist]:
    pl = await get_playlist(db, playlist_id)
    if not pl:
        return None
    pl.name = name
    if icon is not None:
        pl.icon = icon
    await db.commit()
    await db.refresh(pl)
    return pl


async def delete_playlist(db: AsyncSession, playlist_id: str) -> bool:
    pl = await get_playlist(db, playlist_id)
    if not pl:
        return False
    await db.delete(pl)
    await db.commit()
    return True


async def get_playlist_songs(db: AsyncSession, playlist_id: str) -> list[Song]:
    result = await db.execute(
        select(Song)
        .join(PlaylistSong, Song.uuid == PlaylistSong.song_uuid)
        .where(PlaylistSong.playlist_id == playlist_id)
        .order_by(PlaylistSong.position.asc())
    )
    return list(result.scalars().all())


async def bulk_add_songs_to_playlist(db: AsyncSession, playlist_id: str, song_uuids: list[str]) -> None:
    result = await db.execute(
        select(func.max(PlaylistSong.position)).where(PlaylistSong.playlist_id == playlist_id)
    )
    max_pos = result.scalar_one_or_none() or -1
    existing_result = await db.execute(
        select(PlaylistSong.song_uuid).where(PlaylistSong.playlist_id == playlist_id)
    )
    existing = {row[0] for row in existing_result.all()}
    position = max_pos + 1
    for song_uuid in song_uuids:
        if song_uuid not in existing:
            db.add(PlaylistSong(playlist_id=playlist_id, song_uuid=song_uuid, position=position))
            existing.add(song_uuid)
            position += 1
    await db.commit()


async def add_song_to_playlist(db: AsyncSession, playlist_id: str, song_uuid: str) -> bool:
    result = await db.execute(
        select(func.max(PlaylistSong.position)).where(PlaylistSong.playlist_id == playlist_id)
    )
    max_pos = result.scalar_one_or_none() or -1
    ps = PlaylistSong(playlist_id=playlist_id, song_uuid=song_uuid, position=max_pos + 1)
    db.add(ps)
    try:
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        return False


async def remove_song_from_playlist(db: AsyncSession, playlist_id: str, song_uuid: str) -> bool:
    result = await db.execute(
        select(PlaylistSong).where(
            PlaylistSong.playlist_id == playlist_id,
            PlaylistSong.song_uuid == song_uuid,
        )
    )
    ps = result.scalar_one_or_none()
    if not ps:
        return False
    await db.delete(ps)
    await db.commit()
    return True


async def bulk_remove_songs_from_playlist(db: AsyncSession, playlist_id: str, song_uuids: list[str]) -> None:
    await db.execute(
        delete(PlaylistSong).where(
            PlaylistSong.playlist_id == playlist_id,
            PlaylistSong.song_uuid.in_(song_uuids),
        )
    )
    await db.commit()


async def reorder_playlist(db: AsyncSession, playlist_id: str, song_uuids: list[str]) -> bool:
    """Replace the playlist order with the given ordered list of song UUIDs."""
    result = await db.execute(
        select(PlaylistSong).where(PlaylistSong.playlist_id == playlist_id)
    )
    existing = {ps.song_uuid: ps for ps in result.scalars().all()}
    for i, uuid in enumerate(song_uuids):
        if uuid in existing:
            existing[uuid].position = i
    await db.commit()
    return True


async def get_offline_song_ids(db: AsyncSession, user_id: str) -> list[str]:
    result = await db.execute(
        select(UserOfflineSong.song_id).where(UserOfflineSong.user_id == user_id)
    )
    return list(result.scalars().all())


async def add_offline_song(db: AsyncSession, user_id: str, song_id: str) -> None:
    existing = await db.execute(
        select(UserOfflineSong).where(
            UserOfflineSong.user_id == user_id,
            UserOfflineSong.song_id == song_id,
        )
    )
    if existing.scalar_one_or_none():
        return
    db.add(UserOfflineSong(user_id=user_id, song_id=song_id))
    await db.commit()


async def remove_offline_song(db: AsyncSession, user_id: str, song_id: str) -> None:
    await db.execute(
        delete(UserOfflineSong).where(
            UserOfflineSong.user_id == user_id,
            UserOfflineSong.song_id == song_id,
        )
    )
    await db.commit()


async def sync_offline_songs(db: AsyncSession, user_id: str, local_ids: list[str]) -> list[str]:
    """Upsert all local_ids for this user; return ids that are on server but not in local_ids."""
    server_ids = set(await get_offline_song_ids(db, user_id))
    local_set = set(local_ids)
    for song_id in local_set - server_ids:
        db.add(UserOfflineSong(user_id=user_id, song_id=song_id))
    await db.commit()
    return list(server_ids - local_set)


async def clear_offline_songs(db: AsyncSession, user_id: str) -> None:
    await db.execute(delete(UserOfflineSong).where(UserOfflineSong.user_id == user_id))
    await db.commit()
