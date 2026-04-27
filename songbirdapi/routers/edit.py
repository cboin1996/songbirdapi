import os
import shutil
import uuid as _uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .. import database
from ..dependencies import get_current_user, get_db, load_settings
from ..models import EditJobStatus, Role, Song, User
from .. import crud
from ..editor import apply_edits
from sqlalchemy.ext.asyncio import AsyncSession

_config = load_settings()

router = APIRouter(prefix="/edit", tags=["edit"])


class CutRange(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    fade_in: float = Field(default=0.0, ge=0)
    fade_out: float = Field(default=0.0, ge=0)


class FadeRange(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    type: Literal['in', 'out']


class EditParams(BaseModel):
    trim_start: float = Field(default=0.0, ge=0)
    trim_end: float | None = Field(default=None, ge=0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    fades: list[FadeRange] = Field(default_factory=list)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    normalize: bool = Field(default=False)
    cuts: list[CutRange] = Field(default_factory=list)


class EditRequest(BaseModel):
    params: EditParams
    overwrite: bool = False


class EditJobResponse(BaseModel):
    job_id: str
    status: str
    result_song_id: str | None = None
    error: str | None = None


async def _run_edit_job(job_id: str, source_song_id: str, user_id: str, params: dict, overwrite: bool) -> None:
    async with database._session_factory() as db:
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
            # Always edit from the root original to avoid compounding generation loss.
            root_id = source.root_song_id or source.uuid
            root = await crud.get_song(db, root_id) if root_id != source.uuid else source

            new_uuid = str(_uuid.uuid4())
            dest_path = os.path.join(_config.downloads_dir, f"{new_uuid}.mp3")
            try:
                await apply_edits(root.file_path, dest_path, params)
                new_song = Song(
                    uuid=new_uuid,
                    url=source.url,
                    file_path=dest_path,
                    properties=source.properties,
                    artwork_thumb=source.artwork_thumb,
                    artwork_full=source.artwork_full,
                    parent_song_id=source_song_id,
                    root_song_id=root_id,
                )
                db.add(new_song)
                await db.commit()

                # Remove source from library — it becomes the hidden "last save"
                await crud.remove_from_library(db, user_id, source_song_id)

                # Enforce 2-edit cap: delete the old grandparent (pre-last-save) if it
                # is not the root and has no other library references.
                if source.parent_song_id and source.parent_song_id != root_id:
                    if await crud.library_ref_count(db, source.parent_song_id) == 0:
                        await crud.delete_song(db, source.parent_song_id)

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


class DraftResponse(BaseModel):
    params: EditParams
    updated_at: str


class DraftSummaryResponse(BaseModel):
    song_id: str
    properties: dict | None
    artwork_cached: bool
    updated_at: str


@router.get("/drafts", response_model=list[DraftSummaryResponse])
async def list_drafts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await crud.list_user_drafts(db, current_user.id)


@router.get("/songs/{id}/draft", response_model=DraftResponse)
async def get_draft(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    draft = await crud.get_edit_draft(db, current_user.id, id)
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no draft")
    return DraftResponse(params=EditParams(**draft.params), updated_at=draft.updated_at.isoformat())


@router.put("/songs/{id}/draft", status_code=status.HTTP_204_NO_CONTENT)
async def save_draft(
    id: str,
    body: EditParams,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    song = await crud.get_song(db, id)
    if not song:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="song not found")
    await crud.upsert_edit_draft(db, current_user.id, id, body.model_dump())


@router.delete("/songs/{id}/draft", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await crud.delete_edit_draft(db, current_user.id, id)


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
