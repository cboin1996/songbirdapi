from typing import Annotated, List, Optional, Union
from fastapi import APIRouter, Query, status
from fastapi import HTTPException
from fastapi.logger import logger
from pydantic import BaseModel, Field, Json
import os
import logging
from songbirdcore import itunes
from songbirdcore.models.itunes_api import ItunesApiAlbumKeys, ItunesApiSongModel
from songbirdcore.models.modes import Modes
from starlette.status import HTTP_404_NOT_FOUND

from ..dependencies import load_redis, load_settings, process_song_url
from .downloads import DownloadCachedSong

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)

config = load_settings()
db = load_redis(config)

ROUTE_NAME = "properties"
router = APIRouter(
    prefix=f"/{ROUTE_NAME}",
    tags=[ROUTE_NAME],
)


class TaggedCachedSong(BaseModel):
    uuid: str
    properties: ItunesApiSongModel
    url: str
    file_path: str


class TagResponse(BaseModel):
    song_id: str


class ItunesFilterParams(BaseModel):
    limit: int = Field(10, gt=0, le=50)
    """limit of values to return"""
    query: str
    """value to search itunes for"""
    mode: Modes = Modes.SONG
    """the mode to choose from"""
    lookup: bool = False
    """whether to perform an itunes general search, or a focused search with an id"""


@router.get("/itunes")
async def get_properties_itunes(
    filter_query: Annotated[ItunesFilterParams, Query()],
) -> List[Union[ItunesApiSongModel, ItunesApiAlbumKeys]]:
    """
    Query the itunes earch api
    """
    response = itunes.query_api(
        search_variable=filter_query.query,
        limit=filter_query.limit,
        mode=filter_query.mode,
        lookup=filter_query.lookup,
    )
    return response


class FilterParams(BaseModel):
    query: str

@router.get("/")
async def get_properties(filter_query: Annotated[FilterParams, Query()]):
    res = await db.simple_search(config.redis_song_index_name, filter_query.query)
    return res

@router.get("/{id}")
async def get_properties_id(id: str) -> ItunesApiSongModel:
    """Get song properties for a given URL"""
    res: Optional[DownloadCachedSong] = await db.index_get(
        config.redis_song_index_prefix, id, DownloadCachedSong
    )
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No song downloaded for url {id}",
        )
    if not res.properties:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Song exists, but no properties found. Use PUT /{ROUTE_NAME} to set them.",
        )

    return res.properties

class TagBody(BaseModel):
    properties: ItunesApiSongModel
    song_id: str

@router.put("/")
async def put_properties(
    body: TagBody,
) -> TagResponse:
    downloaded_song: Optional[DownloadCachedSong] = await db.index_get(
        config.redis_song_index_prefix, body.song_id, DownloadCachedSong
    )  # pyright: ignore
    if not downloaded_song:
        msg = f"Cannot tag song w/ id {body.song_id}, it has not been downloaded yet!"
        logger.error(msg)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
    if not os.path.exists(downloaded_song.file_path):
        msg = f"Cannot tag file {downloaded_song.file_path}, file does not exist"
        logger.error(msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg
        )
    # TODO: are the tags working properly?
    result = itunes.mp3ID3Tagger(downloaded_song.file_path, body.properties)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not tag file with properties from body {body.properties.model_dump_json()}",
        )

    # save results in db
    # add item to index: https://redis.readthedocs.io/en/stable/examples/search_json_examples.html#Searching
    downloaded_song.properties = body.properties
    # cast to int as index expects number field
    downloaded_song.properties.collectionId = str(downloaded_song.properties.collectionId)
    await db.index(
        config.redis_song_index_prefix, body.song_id, downloaded_song.model_dump()
    )
    # update the download cache with the properties
    return TagResponse(song_id=body.song_id)
