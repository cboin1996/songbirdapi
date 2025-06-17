from http import HTTPStatus
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.logger import logger
from typing import Optional
from fastapi.responses import FileResponse
from songbirdcore import youtube
from songbirdcore import itunes
from pydantic import BaseModel
import uuid
import os
from ..settings import SongbirdServerConfig
from ..dependencies import load_settings
import logging

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)

# add router for all songbird related api calls
router = APIRouter(
    prefix="/download",
    tags=["download"],
)

from songbirdcore.models.itunes_api import ItunesApiSongModel
class DownloadBody(BaseModel):
    url: str
    song_properties: Optional[ItunesApiSongModel]

@router.post("/download", response_model=None)
async def download(
    body: DownloadBody,
    config: SongbirdServerConfig = Depends(load_settings)
):
    file_id = str(uuid.uuid4())
    file_path = os.path.join(config.downloads_dir, file_id)
    embed_thumbnail = False
    if not body:
        embed_thumbnail = True

    result = youtube.run_download(
        url=body.url,
        file_path_no_format=file_path,
        file_format="mp3",
        embed_thumbnail=embed_thumbnail
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not perform download of song at url {body.url}"
        )
    if not body.song_properties: 
        return FileResponse(file_path)

    result = itunes.mp3ID3Tagger(file_path, body.song_properties)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not tag file with properties from body {body.song_properties.model_dump_json()}"
        )
