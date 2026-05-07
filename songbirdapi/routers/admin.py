import shutil
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import cast, or_, Date, func, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from songbirdapi import crud
from songbirdapi.models import (
    EditJob,
    EditJobStatus,
    ErrorLog,
    ImportJob,
    Role,
    Song,
    SongDownload,
    SongPlay,
    SongShareToken,
    User,
    UserSong,
)
from songbirdapi.routers.auth import UserResponse
from songbirdapi.security import verify_password
from ..dependencies import get_db, get_current_user, load_settings, require_admin

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


class UpdateUserBody(BaseModel):
    role: Optional[Role] = None
    is_active: Optional[bool] = None


class DeleteUserBody(BaseModel):
    password: str


class UsersPage(BaseModel):
    total: int
    users: List[UserResponse]


@router.get("/users", response_model=UsersPage)
async def list_users(
    query: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    base = select(User)
    if query:
        pattern = f"%{query}%"
        base = base.where(
            or_(
                User.username.ilike(pattern),
                User.email.ilike(pattern),
                cast(User.role, String).ilike(pattern),
            )
        )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    result = await db.execute(base.order_by(User.username).offset(offset).limit(limit))
    return UsersPage(total=total, users=list(result.scalars().all()))


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str, body: UpdateUserBody, db: AsyncSession = Depends(get_db)
):
    user = await crud.update_user(db, user_id, role=body.role, is_active=body.is_active)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    body: DeleteUserBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await verify_password(body.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password"
        )
    deleted = await crud.delete_user(db, user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )


class AdminImportJobResponse(BaseModel):
    job_id: str
    user_id: str
    username: str
    status: str
    song_id: Optional[str] = None
    track_name: Optional[str] = None
    error: Optional[str] = None
    duplicate_of: Optional[str] = None
    filename: Optional[str] = None
    created_at: Optional[datetime] = None


class AdminImportJobsPage(BaseModel):
    total: int
    jobs: List[AdminImportJobResponse]
    status_counts: dict[str, int] = {}


@router.get("/imports", response_model=AdminImportJobsPage)
async def list_all_imports(
    query: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    base = (
        select(ImportJob)
        .outerjoin(Song, ImportJob.song_id == Song.uuid)
        .outerjoin(User, ImportJob.user_id == User.id)
    )
    if query:
        pattern = f"%{query}%"
        base = base.where(
            or_(
                cast(ImportJob.status, String).ilike(pattern),
                ImportJob.filename.ilike(pattern),
                Song.properties["trackName"].astext.ilike(pattern),
                User.username.ilike(pattern),
            )
        )

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    counts_base = select(ImportJob.status, func.count())
    if query:
        counts_base = (
            counts_base.outerjoin(Song, ImportJob.song_id == Song.uuid)
            .outerjoin(User, ImportJob.user_id == User.id)
            .where(
                or_(
                    cast(ImportJob.status, String).ilike(f"%{query}%"),
                    ImportJob.filename.ilike(f"%{query}%"),
                    Song.properties["trackName"].astext.ilike(f"%{query}%"),
                    User.username.ilike(f"%{query}%"),
                )
            )
        )
    counts_rows = (await db.execute(counts_base.group_by(ImportJob.status))).all()
    status_counts = {row[0].value: row[1] for row in counts_rows}

    result = await db.execute(
        base.order_by(ImportJob.created_at.desc()).offset(offset).limit(limit)
    )
    jobs = list(result.scalars().all())

    user_ids = {j.user_id for j in jobs}
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    users_by_id = {u.id: u for u in users_result.scalars()}

    responses = []
    for job in jobs:
        track_name: str | None = None
        if job.song_id:
            song = await crud.get_song(db, job.song_id)
            if song and song.properties:
                track_name = song.properties.get("trackName")
        u = users_by_id.get(job.user_id)
        responses.append(
            AdminImportJobResponse(
                job_id=job.id,
                user_id=job.user_id,
                username=u.username if u else "unknown",
                status=job.status.value,
                song_id=job.song_id,
                track_name=track_name,
                error=job.error,
                duplicate_of=job.duplicate_of,
                filename=job.filename,
                created_at=job.created_at,
            )
        )
    return AdminImportJobsPage(total=total, jobs=responses, status_counts=status_counts)


class EditJobSummary(BaseModel):
    job_id: str
    source_song_id: str
    user_id: str
    status: str
    result_song_id: Optional[str]
    error: Optional[str]
    created_at: datetime
    updated_at: datetime


class DayActivity(BaseModel):
    date: str
    plays: int
    downloads: int


class TopSong(BaseModel):
    song_id: str
    title: Optional[str]
    artist: Optional[str]
    count: int


class PerUser(BaseModel):
    user_id: str
    username: str
    song_count: int
    play_count: int
    download_count: int
    last_active: Optional[str]


class AdminStats(BaseModel):
    song_count: int
    user_count: int
    disk_bytes: int
    disk_total: int
    disk_free: int
    edit_job_count: int
    failed_job_count: int
    error_log_count: int
    active_share_tokens: int
    import_count: int
    import_failed_count: int
    import_duplicate_count: int
    recent_jobs: List[EditJobSummary]
    plays_by_day: List[DayActivity]
    top_songs: List[TopSong]
    per_user: List[PerUser]


@router.get("/stats", response_model=AdminStats)
async def get_stats(db: AsyncSession = Depends(get_db)):
    config = load_settings()

    song_count = (await db.execute(select(func.count()).select_from(Song))).scalar_one()
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    disk_usage = shutil.disk_usage(config.downloads_dir)

    edit_job_count = (
        await db.execute(select(func.count()).select_from(EditJob))
    ).scalar_one()
    failed_job_count = (
        await db.execute(
            select(func.count())
            .select_from(EditJob)
            .where(EditJob.status == EditJobStatus.failed)
        )
    ).scalar_one()
    error_log_count = (
        await db.execute(select(func.count()).select_from(ErrorLog))
    ).scalar_one()

    import_count = (
        await db.execute(select(func.count()).select_from(ImportJob))
    ).scalar_one()
    import_failed_count = (
        await db.execute(
            select(func.count())
            .select_from(ImportJob)
            .where(ImportJob.status == EditJobStatus.failed)
        )
    ).scalar_one()
    import_duplicate_count = (
        await db.execute(
            select(func.count())
            .select_from(ImportJob)
            .where(ImportJob.duplicate_of.isnot(None))
        )
    ).scalar_one()

    now = datetime.now(tz=timezone.utc)
    active_share_tokens = (
        await db.execute(
            select(func.count())
            .select_from(SongShareToken)
            .where(SongShareToken.expires_at > now)
        )
    ).scalar_one()

    jobs_result = await db.execute(
        select(EditJob).order_by(EditJob.created_at.desc()).limit(10)
    )
    jobs = list(jobs_result.scalars().all())

    # plays_by_day: last 7 days
    seven_days_ago = now - timedelta(days=7)
    plays_by_day_result = await db.execute(
        select(
            cast(SongPlay.played_at, Date).label("day"),
            func.count().label("cnt"),
        )
        .where(SongPlay.played_at >= seven_days_ago)
        .group_by(cast(SongPlay.played_at, Date))
    )
    plays_by_day_map: dict[str, dict] = {}
    for row in plays_by_day_result:
        plays_by_day_map[str(row.day)] = {"plays": row.cnt, "downloads": 0}

    downloads_by_day_result = await db.execute(
        select(
            cast(SongDownload.downloaded_at, Date).label("day"),
            func.count().label("cnt"),
        )
        .where(SongDownload.downloaded_at >= seven_days_ago)
        .group_by(cast(SongDownload.downloaded_at, Date))
    )
    for row in downloads_by_day_result:
        key = str(row.day)
        if key not in plays_by_day_map:
            plays_by_day_map[key] = {"plays": 0, "downloads": 0}
        plays_by_day_map[key]["downloads"] = row.cnt

    plays_by_day = [
        DayActivity(date=d, plays=v["plays"], downloads=v["downloads"])
        for d, v in sorted(plays_by_day_map.items())
    ]

    # top_songs: top 5 by all-time play count
    top_songs_result = await db.execute(
        select(
            SongPlay.song_id,
            func.count().label("cnt"),
        )
        .group_by(SongPlay.song_id)
        .order_by(func.count().desc())
        .limit(5)
    )
    top_song_rows = list(top_songs_result)
    top_song_ids = [r.song_id for r in top_song_rows]
    top_song_map: dict[str, Song] = {}
    if top_song_ids:
        songs_result = await db.execute(select(Song).where(Song.uuid.in_(top_song_ids)))
        for s in songs_result.scalars():
            top_song_map[s.uuid] = s

    top_songs = [
        TopSong(
            song_id=r.song_id,
            title=(
                (top_song_map[r.song_id].properties or {}).get("trackName")
                if r.song_id in top_song_map
                else None
            ),
            artist=(
                (top_song_map[r.song_id].properties or {}).get("artistName")
                if r.song_id in top_song_map
                else None
            ),
            count=r.cnt,
        )
        for r in top_song_rows
    ]

    # per_user
    users_result = await db.execute(select(User))
    all_users = list(users_result.scalars())

    user_song_counts_result = await db.execute(
        select(UserSong.user_id, func.count().label("cnt")).group_by(UserSong.user_id)
    )
    user_song_counts = {r.user_id: r.cnt for r in user_song_counts_result}

    user_play_counts_result = await db.execute(
        select(SongPlay.user_id, func.count().label("cnt")).group_by(SongPlay.user_id)
    )
    user_play_counts = {r.user_id: r.cnt for r in user_play_counts_result}

    user_dl_counts_result = await db.execute(
        select(SongDownload.user_id, func.count().label("cnt")).group_by(
            SongDownload.user_id
        )
    )
    user_dl_counts = {r.user_id: r.cnt for r in user_dl_counts_result}

    user_last_play_result = await db.execute(
        select(SongPlay.user_id, func.max(SongPlay.played_at).label("last")).group_by(
            SongPlay.user_id
        )
    )
    user_last_play = {r.user_id: r.last for r in user_last_play_result}

    per_user = [
        PerUser(
            user_id=u.id,
            username=u.username,
            song_count=user_song_counts.get(u.id, 0),
            play_count=user_play_counts.get(u.id, 0),
            download_count=user_dl_counts.get(u.id, 0),
            last_active=(
                user_last_play[u.id].isoformat() if u.id in user_last_play else None
            ),
        )
        for u in all_users
    ]

    return AdminStats(
        song_count=song_count,
        user_count=user_count,
        disk_bytes=disk_usage.used,
        disk_total=disk_usage.total,
        disk_free=disk_usage.free,
        edit_job_count=edit_job_count,
        failed_job_count=failed_job_count,
        error_log_count=error_log_count,
        active_share_tokens=active_share_tokens,
        import_count=import_count,
        import_failed_count=import_failed_count,
        import_duplicate_count=import_duplicate_count,
        recent_jobs=[
            EditJobSummary(
                job_id=j.id,
                source_song_id=j.source_song_id,
                user_id=j.user_id,
                status=j.status.value,
                result_song_id=j.result_song_id,
                error=j.error,
                created_at=j.created_at,
                updated_at=j.updated_at,
            )
            for j in jobs
        ],
        plays_by_day=plays_by_day,
        top_songs=top_songs,
        per_user=per_user,
    )


class EditJobsPage(BaseModel):
    total: int
    jobs: List[EditJobSummary]
    status_counts: dict[str, int] = {}


@router.get("/edit-jobs", response_model=EditJobsPage)
async def get_edit_jobs(
    query: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    base = select(EditJob)
    if query:
        pattern = f"%{query}%"
        base = base.where(
            or_(
                cast(EditJob.status, String).ilike(pattern),
                EditJob.error.ilike(pattern),
                EditJob.user_id.ilike(pattern),
                EditJob.id.ilike(pattern),
            )
        )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    counts_base = select(EditJob.status, func.count())
    if query:
        pattern = f"%{query}%"
        counts_base = counts_base.where(
            or_(
                cast(EditJob.status, String).ilike(pattern),
                EditJob.error.ilike(pattern),
                EditJob.user_id.ilike(pattern),
                EditJob.id.ilike(pattern),
            )
        )
    counts_rows = (await db.execute(counts_base.group_by(EditJob.status))).all()
    status_counts = {row[0].value: row[1] for row in counts_rows}

    result = await db.execute(
        base.order_by(EditJob.created_at.desc()).offset(offset).limit(limit)
    )
    jobs = list(result.scalars().all())
    return EditJobsPage(
        total=total,
        status_counts=status_counts,
        jobs=[
            EditJobSummary(
                job_id=j.id,
                source_song_id=j.source_song_id,
                user_id=j.user_id,
                status=j.status.value,
                result_song_id=j.result_song_id,
                error=j.error,
                created_at=j.created_at,
                updated_at=j.updated_at,
            )
            for j in jobs
        ],
    )


class ErrorLogEntry(BaseModel):
    id: str
    timestamp: datetime
    level: str
    path: Optional[str]
    method: Optional[str]
    status_code: Optional[int]
    message: str
    detail: Optional[str]
    user_id: Optional[str]


class ErrorsPage(BaseModel):
    total: int
    errors: List[ErrorLogEntry]
    source_counts: dict[str, int] = {}


@router.get("/errors", response_model=ErrorsPage)
async def get_errors(
    query: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    error_log_base = select(ErrorLog)
    failed_job_base = select(EditJob).where(EditJob.status == EditJobStatus.failed)
    if query:
        pattern = f"%{query}%"
        error_log_base = error_log_base.where(
            or_(
                ErrorLog.message.ilike(pattern),
                ErrorLog.path.ilike(pattern),
                ErrorLog.method.ilike(pattern),
                cast(ErrorLog.status_code, String).ilike(pattern),
                ErrorLog.user_id.ilike(pattern),
            )
        )
        failed_job_base = failed_job_base.where(
            or_(
                EditJob.error.ilike(pattern),
                EditJob.user_id.ilike(pattern),
            )
        )

    error_log_count = (
        await db.execute(select(func.count()).select_from(error_log_base.subquery()))
    ).scalar_one()
    failed_job_count_errors = (
        await db.execute(select(func.count()).select_from(failed_job_base.subquery()))
    ).scalar_one()
    total = error_log_count + failed_job_count_errors

    error_logs_result = await db.execute(
        error_log_base.order_by(ErrorLog.timestamp.desc()).offset(offset).limit(limit)
    )
    error_rows = list(error_logs_result.scalars())

    failed_jobs_result = await db.execute(
        failed_job_base.order_by(EditJob.created_at.desc()).offset(offset).limit(limit)
    )
    failed_jobs = list(failed_jobs_result.scalars())

    entries: list[ErrorLogEntry] = [
        ErrorLogEntry(
            id=e.id,
            timestamp=e.timestamp,
            level=e.level,
            path=e.path,
            method=e.method,
            status_code=e.status_code,
            message=e.message,
            detail=e.detail,
            user_id=e.user_id,
        )
        for e in error_rows
    ]
    entries += [
        ErrorLogEntry(
            id=j.id,
            timestamp=j.created_at,
            level="error",
            path=None,
            method=None,
            status_code=None,
            message=f"edit job failed: {j.error or 'unknown'}",
            detail=None,
            user_id=j.user_id,
        )
        for j in failed_jobs
    ]
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    source_counts: dict[str, int] = {}
    if error_log_count > 0:
        source_counts["error_log"] = error_log_count
    if failed_job_count_errors > 0:
        source_counts["failed_edit_job"] = failed_job_count_errors
    return ErrorsPage(total=total, errors=entries[:limit], source_counts=source_counts)
