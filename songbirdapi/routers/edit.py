import os
import shutil
import uuid as _uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..database import _session_factory
from ..dependencies import get_current_user, get_db, load_settings
from ..models import EditJobStatus, Role, Song, User
from .. import crud
from ..editor import apply_edits
from sqlalchemy.ext.asyncio import AsyncSession

_config = load_settings()

router = APIRouter(prefix="/edit", tags=["edit"])


class EditParams(BaseModel):
    trim_start: float = Field(default=0.0, ge=0)
    trim_end: float | None = Field(default=None, ge=0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    fade_in: float = Field(default=0.0, ge=0)
    fade_out: float = Field(default=0.0, ge=0)


class EditRequest(BaseModel):
    params: EditParams
    overwrite: bool = False


class EditJobResponse(BaseModel):
    job_id: str
    status: str
    result_song_id: str | None = None
    error: str | None = None


async def _run_edit_job(job_id: str, source_song_id: str, user_id: str, params: dict, overwrite: bool) -> None:
    async with _session_factory() as db:
        await crud.update_edit_job(db, job_id, EditJobStatus.processing)

        source = await crud.get_song(db, source_song_id)
        if not source:
            await crud.update_edit_job(db, job_id, EditJobStatus.failed, error="source song not found")
            return

        if overwrite:
            dest_path = source.file_path
            tmp_path = dest_path + ".tmp"
            try:
                await apply_edits(source.file_path, tmp_path, params)
                os.replace(tmp_path, dest_path)
                await crud.update_edit_job(db, job_id, EditJobStatus.done, result_song_id=source_song_id)
            except Exception as exc:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                await crud.update_edit_job(db, job_id, EditJobStatus.failed, error=str(exc))
        else:
            new_uuid = str(_uuid.uuid4())
            dest_path = os.path.join(_config.downloads_dir, f"{new_uuid}.mp3")
            try:
                await apply_edits(source.file_path, dest_path, params)
                new_song = Song(
                    uuid=new_uuid,
                    url=source.url,
                    file_path=dest_path,
                    properties=source.properties,
                    artwork_thumb=source.artwork_thumb,
                    artwork_full=source.artwork_full,
                    parent_song_id=source_song_id,
                )
                db.add(new_song)
                await db.commit()
                await crud.add_to_library(db, user_id, new_uuid)
                await crud.update_edit_job(db, job_id, EditJobStatus.done, result_song_id=new_uuid)
            except Exception as exc:
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                await crud.update_edit_job(db, job_id, EditJobStatus.failed, error=str(exc))


@router.post("/songs/{id}", response_model=EditJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_edit_job(
    id: str,
    body: EditRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.overwrite and current_user.role != Role.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="only admins can overwrite originals")

    song = await crud.get_song(db, id)
    if not song:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="song not found")

    job = await crud.create_edit_job(db, id, current_user.id, body.params.model_dump())
    background_tasks.add_task(_run_edit_job, job.id, id, current_user.id, body.params.model_dump(), body.overwrite)
    return EditJobResponse(job_id=job.id, status=job.status.value)


@router.get("/jobs/{job_id}", response_model=EditJobResponse)
async def get_edit_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await crud.get_edit_job(db, job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return EditJobResponse(
        job_id=job.id,
        status=job.status.value,
        result_song_id=job.result_song_id,
        error=job.error,
    )
