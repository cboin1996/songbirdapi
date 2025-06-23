import enum
from http import HTTPStatus
import json
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.logger import logger
from typing import Any, List, Optional, Set, Union
from fastapi.responses import FileResponse
from songbirdcore import youtube
from songbirdcore import itunes
from songbirdcore.models.itunes_api import ItunesApiSongModel
from pydantic import BaseModel, Json, ValidationError
import uuid
import os

from songbirdapi.dbclient import RedisClient
from ..settings import SongbirdServerConfig
from ..dependencies import load_redis, load_settings, process_song_url
import logging

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)

# add router for all songbird related api calls
router = APIRouter(
    prefix="/download",
    tags=["download"],
)
config = load_settings()
db = load_redis(config)

class FileFormats(enum.StrEnum):
    mp3="mp3"
    m4a="m4a"

class DownloadBody(BaseModel):
    url: str
    ignore_cache: bool = False
    embed_thumbnail: bool = False
    file_format: FileFormats = FileFormats.mp3
    """override cache check, downloading same song to new file"""


class DownloadResponse(BaseModel):
    song_ids: Set[str]


def ensureDict(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    if not isinstance(value, dict):
        raise ValidationError(f"validation error. value {value} must be dict.")

class DownloadCachedSong(BaseModel):
    file_path: str
    url: str
    properties: Optional[ItunesApiSongModel] = None
    uuid: str

@router.post("/")
async def download(
    body: DownloadBody,
) -> DownloadResponse:
    # split off any playlists from youtube
    # TODO: add logic to songbirdcore?
    url = process_song_url(body.url)
    res = await db.smembers(config.redis_song_url_prefix, url)
    if res and not body.ignore_cache:
        logger.info(f"returning cached values {res}")
        return DownloadResponse(song_ids=res)

    song_id = str(uuid.uuid4())
    file_path = os.path.join(config.downloads_dir, song_id)
    file_path = youtube.run_download(
        url=url, file_path_no_format=file_path, file_format=body.file_format, embed_thumbnail=body.embed_thumbnail
    )

    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not perform download of song at url {url}",
        )

    # we store two ways to lookup, one mapping URL->song_id,
    response = await db.sadd(config.redis_song_url_prefix, url, song_id)
    # the other via uuid which
    # stores more nested data about a song
    uuid_cached_song = DownloadCachedSong(url=url, file_path=file_path, uuid=song_id).model_dump(
        exclude_none=True
    )
    response = await db.index(config.redis_song_index_prefix, song_id, uuid_cached_song)
    logger.info(f"returning downloaded song {song_id}")
    return DownloadResponse(song_ids={song_id})


@router.get("/{id}")
async def get_download(id: str):
    res: Optional[DownloadCachedSong] = await db.index_get(
        config.redis_song_index_prefix, id, DownloadCachedSong
    )
    if res and os.path.exists(res.file_path):
        return FileResponse(res.file_path)
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not find song with id {id}",
        )


@router.delete("/{id}")
async def delete_download(id: str):
    res: Optional[DownloadCachedSong] = await db.index_get(
        config.redis_song_index_prefix, id, DownloadCachedSong
    )
    file_path = os.path.join(config.downloads_dir, id)
    if os.path.exists(file_path):
        os.remove(file_path)
    if res:
        await db.srem(config.redis_song_url_prefix, res.url, id)
    await db.delete(config.redis_song_index_prefix, id)
