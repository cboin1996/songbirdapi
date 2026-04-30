import asyncio
import logging
import os
from typing import Annotated, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.logger import logger
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from songbirdcore import itunes
from songbirdcore.models.itunes_api import ItunesApiAlbumKeys, ItunesApiSongModel
from songbirdcore.models.modes import Modes

from songbirdapi import crud
from ..crud import _is_publish_eligible, _get_missing_fields
from ..database import session_scope
from ..dependencies import get_current_user, get_db, load_settings
from ..models import Role, User

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
    source: Optional[str] = None
    artwork_cached: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _compute(cls, data):
        if hasattr(data, "artwork_thumb"):
            return {
                "uuid": data.uuid,
                "url": data.url,
                "file_path": data.file_path,
                "properties": data.properties,
                "owner_id": data.owner_id,
                "source": getattr(data, "source", None),
                "artwork_cached": data.artwork_thumb is not None,
            }
        return data


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
    return await crud.search_songs(db, filter_query.query, user_id=None)


class EligibilityResponse(BaseModel):
    eligible: bool
    missing_fields: list[str]


@router.get("/{song_id}/eligible", response_model=EligibilityResponse)
async def get_song_eligibility(
    song_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> EligibilityResponse:
    song = await crud.get_song(db, song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Song not found"
        )
    missing = _get_missing_fields(
        song.properties, artwork_cached=song.artwork_thumb is not None
    )
    return EligibilityResponse(eligible=len(missing) == 0, missing_fields=missing)


@router.get("/{id}")
async def get_properties_id(
    id: str, db: AsyncSession = Depends(get_db)
) -> ItunesApiSongModel:
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
    as_original: bool = False


async def _cache_artwork(song_id: str, itunes_url: str) -> None:
    from ..artwork import fetch_and_store_artwork
    from ..database import session_scope

    thumb, full = await fetch_and_store_artwork(song_id, itunes_url, config.artwork_dir)
    if thumb or full:
        async with session_scope() as db:
            await crud.update_song_artwork(db, song_id, thumb, full)


@router.put("")
async def put_properties(
    body: TagBody,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> TagResponse:
    # Open session only for the initial read, release before sync file
    # tagging (mp3ID3Tagger/m4a_tagger are blocking IO), then re-open for
    # the writes. Holding a session across blocking tagger calls pins a
    # pool connection for hundreds of ms per save and exhausts the pool
    # under concurrent edits.
    async with session_scope() as db:
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
        file_path = song.file_path
        existing_artwork_url = (song.properties or {}).get("artworkUrl100", "")

    artwork_url = body.properties.artworkUrl100 or ""
    if not artwork_url.startswith("http"):
        artwork_url = existing_artwork_url

    ext = os.path.splitext(file_path)[1].lower()
    if artwork_url.startswith("http"):
        props_for_tagging = body.properties.model_copy(
            update={"artworkUrl100": artwork_url}
        )
        tagger = itunes.mp3ID3Tagger if ext == ".mp3" else itunes.m4a_tagger
        result = await asyncio.to_thread(tagger, file_path, props_for_tagging)
    else:
        tagger = (
            itunes.mp3ID3TaggerNoArtwork
            if ext == ".mp3"
            else itunes.m4aID3TaggerNoArtwork
        )
        result = await asyncio.to_thread(tagger, file_path, body.properties)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not tag file with properties from body {body.properties.model_dump_json()}",
        )

    props = body.properties.model_dump()
    props["collectionId"] = str(props["collectionId"])

    async with session_scope() as db:
        await crud.update_song_properties(db, body.song_id, props)
        song = await crud.get_song(db, body.song_id)
        if (
            song
            and song.owner_id == current_user.id
            and _is_publish_eligible(
                props, artwork_cached=song.artwork_thumb is not None
            )
        ):
            as_original = body.as_original and current_user.role == Role.admin
            await crud.publish_song(db, body.song_id, as_original=as_original)

    if body.properties.artworkUrl100:
        background_tasks.add_task(
            _cache_artwork, body.song_id, body.properties.artworkUrl100
        )

    return TagResponse(song_id=body.song_id)
