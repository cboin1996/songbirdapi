import enum
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
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from songbirdcore import youtube
from songbirdcore.models.itunes_api import ItunesApiSongModel

from songbirdapi import crud
from songbirdapi.models import Song, User
from ..dependencies import get_current_user, get_db, load_settings, process_song_url

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)

router = APIRouter(
    prefix="/download",
    tags=["download"],
    dependencies=[Depends(get_current_user)],
)
config = load_settings()


class FileFormats(enum.StrEnum):
    mp3 = "mp3"
    m4a = "m4a"


class DownloadBody(BaseModel):
    url: str
    ignore_cache: bool = False
    embed_thumbnail: bool = False
    file_format: FileFormats = FileFormats.mp3
    """override cache check, downloading same song to new file"""


class DownloadResponse(BaseModel):
    song_ids: Set[str]


class DownloadCachedSong(BaseModel):
    file_path: str
    url: str
    properties: Optional[ItunesApiSongModel] = None
    uuid: str


@router.post("/")
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
        return DownloadResponse(song_ids={s.uuid for s in existing})

    song_id = str(uuid.uuid4())
    file_path = os.path.join(config.downloads_dir, song_id)
    file_path = youtube.run_download(
        url=url,
        file_path_no_format=file_path,
        file_format=body.file_format,
        embed_thumbnail=body.embed_thumbnail,
    )

    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not perform download of song at url {url}",
        )

    song = Song(uuid=song_id, url=url, file_path=file_path)
    await crud.insert_song(db, song)
    await crud.record_download(db, song_id, current_user.id)
    logger.info(f"returning downloaded song {song_id}")
    return DownloadResponse(song_ids={song_id})


@router.get("/{id}")
async def get_download(id: str, request: Request, db: AsyncSession = Depends(get_db)):
    song = await crud.get_song(db, id)
    if not song or not os.path.exists(song.file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Song {id} not found")

    file_size = os.path.getsize(song.file_path)
    media_type = mimetypes.guess_type(song.file_path)[0] or "audio/mpeg"
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(song.file_path, media_type=media_type, headers={"Accept-Ranges": "bytes"})

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
        async with await anyio.open_file(song.file_path, "rb") as f:
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
        },
    )


@router.delete("/{id}")
async def delete_download(id: str, db: AsyncSession = Depends(get_db)):
    song = await crud.get_song(db, id)
    if song and os.path.exists(song.file_path):
        os.remove(song.file_path)
    await crud.delete_song(db, id)
