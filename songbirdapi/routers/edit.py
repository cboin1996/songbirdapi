import asyncio
import os
import shutil
import uuid as _uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from songbirdcore import itunes
from songbirdcore.models.itunes_api import ItunesApiSongModel

from .. import database
from ..dependencies import get_current_user, get_db, load_settings
from ..models import EditJobStatus, Role, Song, User
from .. import crud
from ..editor import apply_edits, _is_lossless_eligible
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
    type: Literal["in", "out"]


class EditParams(BaseModel):
    trim_start: float = Field(default=0.0, ge=0)
    trim_end: float | None = Field(default=None, ge=0)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    fades: list[FadeRange] = Field(default_factory=list)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    normalize: bool = Field(default=False)
    cuts: list[CutRange] = Field(default_factory=list)
    properties_overrides: dict | None = None


class EditRequest(BaseModel):
    params: EditParams
    overwrite: bool = False
    as_original: bool = False


class EditJobResponse(BaseModel):
    job_id: str
    status: str
    result_song_id: str | None = None
    error: str | None = None
    lossless: bool | None = None


def _retag_file(file_path: str, merged_props: dict) -> None:
    """Re-tag the file at file_path with the merged properties dict. Raises on failure."""
    ext = os.path.splitext(file_path)[1].lower()
    artwork_url = merged_props.get("artworkUrl100") or ""
    props_for_tagging = ItunesApiSongModel.model_validate(merged_props)
    if artwork_url.startswith("http"):
        ok = (
            itunes.mp3ID3Tagger(file_path, props_for_tagging)
            if ext == ".mp3"
            else itunes.m4a_tagger(file_path, props_for_tagging)
        )
    else:
        ok = (
            itunes.mp3ID3TaggerNoArtwork(file_path, props_for_tagging)
            if ext == ".mp3"
            else itunes.m4aID3TaggerNoArtwork(file_path, props_for_tagging)
        )
    if not ok:
        raise RuntimeError("failed to tag file with merged properties")


async def _run_edit_job(
    job_id: str,
    source_song_id: str,
    user_id: str,
    params: dict,
    overwrite: bool,
    as_original: bool = False,
) -> None:
    # Sessions are scoped tightly here: setup-read → release → ffmpeg/tag IO →
    # finalize-write. Earlier this whole job ran inside one session_scope,
    # which pinned a pool connection for the entire ffmpeg duration
    # (seconds-minutes) and saturated the pool under concurrent edits.
    async with database.session_scope() as db:
        await crud.update_edit_job(db, job_id, EditJobStatus.processing)

        source = await crud.get_song(db, source_song_id)
        if not source:
            await crud.update_edit_job(
                db, job_id, EditJobStatus.failed, error="source song not found"
            )
            return

        prop_overrides = params.get("properties_overrides") or None
        merged_props: dict | None = None
        if prop_overrides:
            merged_props = {**(source.properties or {}), **prop_overrides}
            if (
                "collectionId" in merged_props
                and merged_props["collectionId"] is not None
            ):
                merged_props["collectionId"] = str(merged_props["collectionId"])

        # Snapshot what we need post-IO so the session can be released.
        source_file_path = source.file_path
        source_uuid = source.uuid
        source_url = source.url
        source_owner_id = source.owner_id
        source_artwork_thumb = source.artwork_thumb
        source_artwork_full = source.artwork_full
        source_parent_song_id = source.parent_song_id
        source_properties = source.properties
        root_id = source.root_song_id or source.uuid
        if not overwrite and root_id != source_uuid:
            root = await crud.get_song(db, root_id)
            root_file_path = root.file_path if root else source_file_path
        else:
            root_file_path = source_file_path

    if overwrite:
        dest_path = source_file_path
        base, ext = os.path.splitext(dest_path)
        tmp_path = f"{base}_tmp{ext}"
        try:
            await apply_edits(source_file_path, tmp_path, params)
            os.replace(tmp_path, dest_path)
            if merged_props is not None:
                await asyncio.to_thread(_retag_file, dest_path, merged_props)
            async with database.session_scope() as db:
                if merged_props is not None:
                    await crud.update_song_properties(db, source_song_id, merged_props)
                    if source_owner_id == user_id and crud._is_publish_eligible(
                        merged_props, artwork_cached=source_artwork_thumb is not None
                    ):
                        await crud.publish_song(
                            db, source_song_id, as_original=as_original
                        )
                await crud.update_edit_job(
                    db, job_id, EditJobStatus.done, result_song_id=source_song_id
                )
        except Exception as exc:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            async with database.session_scope() as db:
                await crud.update_edit_job(
                    db, job_id, EditJobStatus.failed, error=str(exc)
                )
    else:
        new_uuid = str(_uuid.uuid4())
        ext = os.path.splitext(root_file_path)[1] or ".mp3"
        dest_path = os.path.join(_config.downloads_dir, f"{new_uuid}{ext}")
        try:
            await apply_edits(root_file_path, dest_path, params)
            final_props = (
                merged_props if merged_props is not None else source_properties
            )
            if merged_props is not None:
                await asyncio.to_thread(_retag_file, dest_path, merged_props)
            async with database.session_scope() as db:
                new_song = Song(
                    uuid=new_uuid,
                    url=source_url,
                    file_path=dest_path,
                    properties=final_props,
                    artwork_thumb=source_artwork_thumb,
                    artwork_full=source_artwork_full,
                    parent_song_id=source_song_id,
                    root_song_id=root_id,
                    owner_id=user_id,
                )
                db.add(new_song)
                await db.commit()

                # Remove source from library — it becomes the hidden "last save"
                await crud.remove_from_library(db, user_id, source_song_id)

                # Enforce 2-edit cap: delete the old grandparent (pre-last-save) if it
                # is not the root and has no other library references.
                if source_parent_song_id and source_parent_song_id != root_id:
                    if (
                        await crud.library_ref_count(db, source_parent_song_id) == 0
                        and await crud.child_ref_count(
                            db, source_parent_song_id, exclude=source_song_id
                        )
                        == 0
                    ):
                        await crud.delete_song(db, source_parent_song_id)
                        source = await crud.get_song(db, source_song_id)
                        if source:
                            source.parent_song_id = root_id
                            await db.commit()

                await crud.add_to_library(db, user_id, new_uuid)
                await crud.update_edit_job(
                    db, job_id, EditJobStatus.done, result_song_id=new_uuid
                )
        except Exception as exc:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            async with database.session_scope() as db:
                await crud.update_edit_job(
                    db, job_id, EditJobStatus.failed, error=str(exc)
                )


@router.post(
    "/songs/{id}", response_model=EditJobResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create_edit_job(
    id: str,
    body: EditRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.overwrite and current_user.role != Role.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only admins can overwrite originals",
        )
    if body.as_original and current_user.role != Role.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only admins can publish as original",
        )

    song = await crud.get_song(db, id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="song not found"
        )

    job = await crud.create_edit_job(db, id, current_user.id, body.params.model_dump())
    background_tasks.add_task(
        _run_edit_job,
        job.id,
        id,
        current_user.id,
        body.params.model_dump(),
        body.overwrite,
        body.as_original,
    )
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
    return DraftResponse(
        params=EditParams(**draft.params), updated_at=draft.updated_at.isoformat()
    )


@router.put("/songs/{id}/draft", status_code=status.HTTP_204_NO_CONTENT)
async def save_draft(
    id: str,
    body: EditParams,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    song = await crud.get_song(db, id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="song not found"
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="job not found"
        )
    params = job.params or {}
    lossless = _is_lossless_eligible(
        volume=params.get("volume") or 1.0,
        fades=[
            f
            for f in (params.get("fades") or [])
            if float(f.get("end", 0)) > float(f.get("start", 0))
        ],
        speed=params.get("speed") or 1.0,
        normalize=params.get("normalize") or False,
        cuts=[
            c
            for c in (params.get("cuts") or [])
            if float(c.get("end", 0)) > float(c.get("start", 0))
        ],
    )
    return EditJobResponse(
        job_id=job.id,
        status=job.status.value,
        result_song_id=job.result_song_id,
        error=job.error,
        lossless=lossless,
    )
