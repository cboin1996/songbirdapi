import logging
from fastapi import Depends, FastAPI
from fastapi.logger import logger
import os
from redis.commands.json.path import Path
import redis.commands.search.aggregation as aggregations
import redis.commands.search.reducers as reducers
from redis.commands.search.field import TagField, NumericField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import NumericFilter, Query


from songbirdapi.dependencies import load_settings, load_redis

from .dbclient import RedisClient

from .routers import itunes, downloads, songs, auth
from .version import version
from .settings import SongbirdServerConfig

app = FastAPI(
    dependencies=[
        Depends(auth.handle_api_key)
    ]
)

app.include_router(itunes.router)
app.include_router(downloads.router)
app.include_router(songs.router)

# configure log level based on that of uvicorn
uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)

async def initialize_db():
    settings = load_settings()
    db = RedisClient(host=settings.redis_host, port=settings.redis_port)
    schema = (
        TagField("$.song.trackName", as_name="trackName"),
        TagField("$.song.artistName", as_name="artistName"),
        TagField("$.song.collectionName", as_name="collectionName"),
        TagField("$.song.artworkUrl100", as_name="artworkUrl100"),
        TagField("$.song.primaryGenreName", as_name="primaryGenreName"),
        NumericField("$.song.trackNumber", as_name="trackNumber"),
        NumericField("$.song.trackCount", as_name="trackCount"),
        TagField("$.song.collectionId", as_name="collectionId"),
        TagField("$.song.collectionArtistName", as_name="collectionArtistName"),
        NumericField("$.song.discNumber", as_name="discNumber"),
        NumericField("$.song.discCount", as_name="discCount"),
        TagField("$.song.releaseDate", as_name="releaseDate"),
        TagField("$.song.releaseDateKey", as_name="releaseDateKey")
    )
    # TODO: name index? by default it is created as b'idx'
    # FIX THIS LOGIC
    res = await db.list_indices()
    if res is not None and b'idx' not in res:
        res = await db.create_index(schema, definition=IndexDefinition(prefix=["song:"], index_type=IndexType.JSON))
        uvicorn_logger.info(f"songs index initialized {res}")

@app.on_event("startup")
async def startup_event():
    # for _dir in settings.dirs: # pyright: ignore
    #     if not os.path.exists(_dir):
    #         logger.info(f"Creating dir {_dir}")
    #         os.mkdir(_dir)
    await initialize_db()
    return True

@app.get("/")
async def root():
    return {f"message": f"welcome to songbirdapi {version}!"}
