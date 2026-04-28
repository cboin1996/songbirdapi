import logging
import os
from typing import Annotated, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.logger import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from songbirdcore import itunes
from songbirdcore.models.itunes_api import ItunesApiAlbumKeys, ItunesApiSongModel
from songbirdcore.models.modes import Modes

from songbirdapi import crud
from ..crud import _is_publish_eligible
from ..dependencies import get_current_user, get_db, load_settings
from ..models import User

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)

config = load_settings()

ROUTE_NAME = "properties"
router = APIRouter(
    prefix=f"/{ROUTE_NAME}",
    tags=[ROUTE_NAME],
    dependencies=[Depends(get_current_user)],
)


class SongResponse(BaseModel):
    uuid: str
    url: str
    file_path: str
    properties: Optional[ItunesApiSongModel]
    owner_id: Optional[str] = None

    model_config = {"from_attributes": True}


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


@router.get("", response_model=List[SongResponse])
async def get_properties(
    filter_query: Annotated[FilterParams, Query()],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await crud.search_songs(db, filter_query.query, user_id=current_user.id)


@router.get("/{id}")
async def get_properties_id(id: str, db: AsyncSession = Depends(get_db)) -> ItunesApiSongModel:
    """Get song properties for a given URL"""
    song = await crud.get_song(db, id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No song downloaded for url {id}",
        )
    if not song.properties:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Song exists, but no properties found. Use PUT /{ROUTE_NAME} to set them.",
        )
    return ItunesApiSongModel.model_validate(song.properties)


class TagBody(BaseModel):
    properties: ItunesApiSongModel
    song_id: str


async def _cache_artwork(song_id: str, itunes_url: str) -> None:
    from ..artwork import fetch_and_store_artwork
    from ..database import _session_factory
    thumb, full = await fetch_and_store_artwork(song_id, itunes_url, config.artwork_dir)
    if thumb or full:
        async with _session_factory() as db:
            await crud.update_song_artwork(db, song_id, thumb, full)


@router.put("")
async def put_properties(
    body: TagBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TagResponse:
    song = await crud.get_song(db, body.song_id)
    if not song:
        msg = f"Cannot tag song w/ id {body.song_id}, it has not been downloaded yet!"
        logger.error(msg)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
    if not os.path.exists(song.file_path):
        msg = f"Cannot tag file {song.file_path}, file does not exist"
        logger.error(msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg
        )
    # TODO: are the tags working properly?
    result = itunes.mp3ID3Tagger(song.file_path, body.properties)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not tag file with properties from body {body.properties.model_dump_json()}",
        )

    props = body.properties.model_dump()
    props["collectionId"] = str(props["collectionId"])
    await crud.update_song_properties(db, body.song_id, props)

    if body.properties.artworkUrl100:
        background_tasks.add_task(_cache_artwork, body.song_id, body.properties.artworkUrl100)

    song = await crud.get_song(db, body.song_id)
    if song and song.owner_id == current_user.id and _is_publish_eligible(props):
        await crud.publish_song(db, body.song_id)

    return TagResponse(song_id=body.song_id)
