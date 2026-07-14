import asyncio
import logging
import mimetypes
import os
import re
import uuid
from typing import AsyncGenerator, Optional, Set

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.logger import logger
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from songbirdcore import itunes, youtube
from songbirdcore.models.itunes_api import ItunesApiSongModel

from songbirdapi import crud
from songbirdapi.database import session_scope
from songbirdapi.models import AudioFormat, ErrorLog, Song, User
from ..dependencies import (
    get_current_user,
    get_db,
    load_settings,
    process_song_url,
    require_admin,
)

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)

router = APIRouter(
    prefix="/download",
    tags=["download"],
    dependencies=[Depends(get_current_user)],
)
config = load_settings()


class DownloadBody(BaseModel):
    url: str = Field(..., max_length=2048)
    ignore_cache: bool = False
    embed_thumbnail: bool = False
    file_format: AudioFormat = AudioFormat.mp3


class DownloadResponse(BaseModel):
    song_ids: Set[str]
    cached: bool = False
    properties: dict | None = None
    artwork_cached: bool = False


class DownloadCachedSong(BaseModel):
    file_path: str
    url: str
    properties: Optional[ItunesApiSongModel] = None
    uuid: str


@router.post("")
async def download(
    body: DownloadBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DownloadResponse:
    url = process_song_url(body.url)
    existing = await crud.get_songs_by_url(db, url)
    if existing and not body.ignore_cache:
        logger.info(f"returning cached values {[s.uuid for s in existing]}")
        for s in existing:
            await crud.record_download(db, s.uuid, current_user.id)
        return DownloadResponse(
            song_ids={s.uuid for s in existing},
            cached=True,
            properties=existing[0].properties,
            artwork_cached=existing[0].artwork_thumb is not None,
        )

    song_id = str(uuid.uuid4())
    file_path = os.path.join(config.downloads_dir, song_id)
    # yt-dlp can run for tens of seconds; offload to a thread so the event
    # loop stays responsive (otherwise other requests stall and the
    # sqlalchemy QueuePool exhausts under any concurrency).
    file_path = await asyncio.to_thread(
        youtube.run_download,
        url=url,
        file_path_no_format=file_path,
        file_format=body.file_format.value,
        embed_thumbnail=body.embed_thumbnail,
    )

    if not file_path:
        err = ErrorLog(
            id=str(uuid.uuid4()),
            level="error",
            path="/download/",
            method="POST",
            status_code=500,
            message=f"yt-dlp failed for url {url}",
        )
        db.add(err)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not perform download of song at url {url}",
        )

    song = Song(uuid=song_id, url=url, file_path=file_path)
    await crud.insert_song(db, song)
    await crud.record_download(db, song_id, current_user.id)

    props = None
    artwork_bytes = None
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".mp3":
            model, artwork_bytes = itunes.mp3_tag_reader(file_path)
        elif ext == ".m4a":
            model, artwork_bytes = itunes.m4a_tag_reader(file_path)
        else:
            model = None
        if model:
            props = model.model_dump()
            props["collectionId"] = str(props["collectionId"])
            await crud.update_song_properties(db, song_id, props)
    except Exception:
        pass

    artwork_cached = False
    if artwork_bytes:
        from ..artwork import store_artwork_from_bytes

        try:
            thumb, full = await store_artwork_from_bytes(
                song_id, artwork_bytes, config.artwork_dir
            )
            if thumb or full:
                await crud.update_song_artwork(db, song_id, thumb, full)
                artwork_cached = True
        except Exception:
            pass

    logger.info(f"returning downloaded song {song_id}")
    return DownloadResponse(
        song_ids={song_id}, properties=props, artwork_cached=artwork_cached
    )


@router.get("/{id}")
async def get_download(id: str, request: Request):
    # Release the DB session BEFORE returning the streaming response.
    # FastAPI keeps Depends(get_db) connections open until the response
    # body finishes streaming — for audio that's seconds per request.
    # Read the metadata, capture the file path, exit the session, then stream.
    async with session_scope() as db:
        song = await crud.get_song(db, id)
        if not song or not os.path.exists(song.file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Song {id} not found"
            )
        file_path = song.file_path

    file_size = os.path.getsize(file_path)
    media_type = mimetypes.guess_type(file_path)[0] or "audio/mpeg"
    range_header = request.headers.get("range")

    # Cache-Control: no-store — the editor mounts 3 WaveSurfer/buffer
    # consumers in parallel that all GET this same URL. Chromium's HTTP
    # cache races on concurrent same-URL writes (ERR_CACHE_WRITE_FAILURE)
    # and the lost fetches break WaveSurfer.load(), which leaves the
    # editor's preview button permanently disabled. no-store skips the
    # cache write entirely.
    if not range_header:
        return FileResponse(
            file_path,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes", "Cache-Control": "no-store"},
        )

    match = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not match:
        raise HTTPException(status_code=416, detail="Invalid Range header")

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1

    if start >= file_size or end >= file_size or start > end:
        raise HTTPException(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
            detail="Range Not Satisfiable",
        )

    chunk_size = end - start + 1

    async def stream() -> AsyncGenerator[bytes, None]:
        async with await anyio.open_file(file_path, "rb") as f:
            await f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                data = await f.read(min(65536, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        stream(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
            "Cache-Control": "no-store",
        },
    )


@router.delete("/{id}")
async def delete_download(
    id: str, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)
):
    if await crud.child_ref_count(db, id) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Song has edited versions and cannot be deleted",
        )
    await crud.delete_song(db, id)
