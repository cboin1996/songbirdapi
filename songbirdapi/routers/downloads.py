import enum
import logging
import os
import uuid
from typing import Optional, Set

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.logger import logger
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from songbirdcore import youtube
from songbirdcore.models.itunes_api import ItunesApiSongModel

from songbirdapi import crud
from songbirdapi.models import Song
from ..dependencies import get_db, load_settings, process_song_url

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)

router = APIRouter(
    prefix="/download",
    tags=["download"],
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
) -> DownloadResponse:
    url = process_song_url(body.url)
    existing = await crud.get_songs_by_url(db, url)
    if existing and not body.ignore_cache:
        logger.info(f"returning cached values {[s.uuid for s in existing]}")
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
    logger.info(f"returning downloaded song {song_id}")
    return DownloadResponse(song_ids={song_id})


@router.get("/{id}")
async def get_download(id: str, db: AsyncSession = Depends(get_db)):
    song = await crud.get_song(db, id)
    if song and os.path.exists(song.file_path):
        return FileResponse(song.file_path)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Could not find song with id {id}",
    )


@router.delete("/{id}")
async def delete_download(id: str, db: AsyncSession = Depends(get_db)):
    song = await crud.get_song(db, id)
    if song and os.path.exists(song.file_path):
        os.remove(song.file_path)
    await crud.delete_song(db, id)
