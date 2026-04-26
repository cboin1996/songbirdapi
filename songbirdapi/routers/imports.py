import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from songbirdcore import itunes

from .. import crud
from ..database import _session_factory
from ..dependencies import get_current_user, get_db, load_settings
from ..models import EditJobStatus, Song, User

_config = load_settings()
router = APIRouter(prefix="/import", tags=["import"])


class ImportJobResponse(BaseModel):
    job_id: str
    status: str
    song_id: str | None = None
    track_name: str | None = None
    error: str | None = None


async def _run_import(job_id: str, dest_path: str, ext: str, user_id: str) -> None:
    async with _session_factory() as db:
        await crud.update_import_job(db, job_id, EditJobStatus.processing)
        try:
            props = None
            try:
                if ext == ".mp3":
                    model = itunes.mp3_tag_reader(dest_path)
                else:
                    model = itunes.m4a_tag_reader(dest_path)
                if model:
                    props = model.model_dump()
            except Exception:
                pass

            song_uuid = os.path.splitext(os.path.basename(dest_path))[0]
            song = Song(uuid=song_uuid, url="", file_path=dest_path, properties=props)
            db.add(song)
            await db.commit()
            await crud.add_to_library(db, user_id, song_uuid)
            await crud.update_import_job(db, job_id, EditJobStatus.done, song_id=song_uuid)
        except Exception as exc:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            await crud.update_import_job(db, job_id, EditJobStatus.failed, error=str(exc))


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_import(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportJobResponse:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".mp3", ".m4a"):
        raise HTTPException(status_code=400, detail="only mp3 and m4a supported")

    new_uuid = str(uuid.uuid4())
    dest_path = os.path.join(_config.downloads_dir, f"{new_uuid}{ext}")

    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    job = await crud.create_import_job(db, current_user.id, file.filename or "")
    background_tasks.add_task(_run_import, job.id, dest_path, ext, current_user.id)
    return ImportJobResponse(job_id=job.id, status=job.status.value)


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
    )
