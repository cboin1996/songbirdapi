import asyncio
import os
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import cast, func, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from songbirdcore import itunes

from .. import crud, database
from ..crud import _is_publish_eligible
from ..dependencies import get_current_user, get_db, load_settings
from ..models import EditJobStatus, ImportJob, Role, Song, User

_config = load_settings()
router = APIRouter(prefix="/import", tags=["import"])
_import_semaphore = asyncio.Semaphore(5)


class ImportJobResponse(BaseModel):
    job_id: str
    status: str
    song_id: str | None = None
    track_name: str | None = None
    error: str | None = None
    duplicate_of: str | None = None
    filename: str | None = None
    created_at: str | None = None


class ImportJobsPage(BaseModel):
    total: int
    jobs: list[ImportJobResponse]
    status_counts: dict[str, int] = {}


async def _run_import(
    job_id: str,
    dest_path: str,
    ext: str,
    user_id: str,
    as_original: bool = False,
    original_filename: str = "",
) -> None:
    async with _import_semaphore:
        async with database.session_scope() as db:
            await crud.update_import_job(db, job_id, EditJobStatus.processing)
            try:
                props = None
                artwork_bytes = None
                try:
                    if ext == ".mp3":
                        model, artwork_bytes = itunes.mp3_tag_reader(dest_path)
                    else:
                        model, artwork_bytes = itunes.m4a_tag_reader(dest_path)
                    if model:
                        props = model.model_dump()
                except Exception:
                    pass

                # fall back to filename stem when ID3 title tag is absent
                if props is None:
                    props = {}
                track_name = props.get("trackName") or ""
                if not track_name.strip():
                    stem = Path(original_filename).stem.strip()
                    if not stem:
                        await crud.update_import_job(
                            db,
                            job_id,
                            EditJobStatus.failed,
                            error="missing track title",
                        )
                        return
                    props["trackName"] = stem
                    track_name = stem
                artist_name = props.get("artistName") or ""

                # duplicate detection
                if track_name and artist_name:
                    existing = await crud.find_song_by_track_artist(
                        db, track_name, artist_name
                    )
                    if existing:
                        if os.path.exists(dest_path):
                            os.remove(dest_path)
                        await crud.update_import_job(
                            db,
                            job_id,
                            EditJobStatus.duplicate,
                            song_id=existing.uuid,
                            duplicate_of=existing.uuid,
                        )
                        return

                song_uuid = os.path.splitext(os.path.basename(dest_path))[0]
                _REQUIRED_NO_ART = [
                    "trackName",
                    "artistName",
                    "collectionName",
                    "primaryGenreName",
                ]
                eligible = (
                    bool(props)
                    and all(bool((props or {}).get(f)) for f in _REQUIRED_NO_ART)
                    and (
                        bool((props or {}).get("artworkUrl100")) or bool(artwork_bytes)
                    )
                )

                if as_original and eligible:
                    owner_id, source = None, None
                elif as_original and not eligible:
                    owner_id, source = user_id, None
                elif eligible:
                    owner_id, source = None, "community"
                else:
                    owner_id, source = user_id, None

                song = Song(
                    uuid=song_uuid,
                    url="",
                    file_path=dest_path,
                    properties=props,
                    owner_id=owner_id,
                    source=source,
                )
                db.add(song)
                await db.commit()
                await crud.add_to_library(db, user_id, song_uuid)
                if artwork_bytes:
                    from ..artwork import store_artwork_from_bytes

                    try:
                        thumb, full = await store_artwork_from_bytes(
                            song_uuid, artwork_bytes, _config.artwork_dir
                        )
                        if thumb or full:
                            await crud.update_song_artwork(db, song_uuid, thumb, full)
                    except Exception:
                        pass
                await crud.update_import_job(
                    db, job_id, EditJobStatus.done, song_id=song_uuid
                )
            except Exception as exc:
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                await crud.update_import_job(
                    db, job_id, EditJobStatus.failed, error=str(exc)
                )


@router.get("")
async def list_imports(
    query: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportJobsPage:
    base = (
        select(ImportJob)
        .outerjoin(Song, ImportJob.song_id == Song.uuid)
        .where(ImportJob.user_id == current_user.id)
    )
    if query:
        pattern = f"%{query}%"
        base = base.where(
            or_(
                cast(ImportJob.status, String).ilike(pattern),
                ImportJob.filename.ilike(pattern),
                Song.properties["trackName"].astext.ilike(pattern),
            )
        )

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    counts_base = (
        select(ImportJob.status, func.count())
        .outerjoin(Song, ImportJob.song_id == Song.uuid)
        .where(ImportJob.user_id == current_user.id)
    )
    if query:
        pattern = f"%{query}%"
        counts_base = counts_base.where(
            or_(
                cast(ImportJob.status, String).ilike(pattern),
                ImportJob.filename.ilike(pattern),
                Song.properties["trackName"].astext.ilike(pattern),
            )
        )
    counts_rows = (await db.execute(counts_base.group_by(ImportJob.status))).all()
    status_counts = {row[0].value: row[1] for row in counts_rows}

    result = await db.execute(
        base.order_by(ImportJob.created_at.desc()).offset(offset).limit(limit)
    )
    jobs = list(result.scalars().all())
    responses = []
    for job in jobs:
        track_name: str | None = None
        if job.song_id:
            song = await crud.get_song(db, job.song_id)
            if song and song.properties:
                track_name = song.properties.get("trackName")
        responses.append(
            ImportJobResponse(
                job_id=job.id,
                status=job.status.value,
                song_id=job.song_id,
                track_name=track_name,
                error=job.error,
                duplicate_of=job.duplicate_of,
                filename=job.filename,
                created_at=job.created_at.isoformat() if job.created_at else None,
            )
        )
    return ImportJobsPage(total=total, jobs=responses, status_counts=status_counts)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_import(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    as_original: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
) -> ImportJobResponse:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".mp3", ".m4a"):
        raise HTTPException(status_code=400, detail="only mp3 and m4a supported")

    if as_original and current_user.role != Role.admin:
        raise HTTPException(
            status_code=403, detail="only admins can import as original"
        )

    new_uuid = str(uuid.uuid4())
    dest_path = os.path.join(_config.downloads_dir, f"{new_uuid}{ext}")

    # Read upload body and write to disk WITHOUT holding a DB session — large
    # uploads otherwise pin a pool connection for the duration of the body
    # transfer, which exhausts the pool under concurrent imports.
    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    async with database.session_scope() as db:
        job = await crud.create_import_job(db, current_user.id, file.filename or "")
        job_id = job.id
        job_status = job.status.value
    background_tasks.add_task(
        _run_import,
        job_id,
        dest_path,
        ext,
        current_user.id,
        as_original,
        file.filename or "",
    )
    return ImportJobResponse(job_id=job_id, status=job_status)


@router.get("/{job_id}")
async def get_import_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportJobResponse:
    job = await crud.get_import_job(db, job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="job not found")

    track_name: str | None = None
    if job.song_id:
        song = await crud.get_song(db, job.song_id)
        if song and song.properties:
            track_name = song.properties.get("trackName")

    return ImportJobResponse(
        job_id=job.id,
        status=job.status.value,
        song_id=job.song_id,
        track_name=track_name,
        error=job.error,
        duplicate_of=job.duplicate_of,
        filename=job.filename,
        created_at=job.created_at.isoformat() if job.created_at else None,
    )
