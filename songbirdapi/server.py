import logging
from fastapi import Depends, FastAPI
from fastapi.logger import logger
from fastapi.middleware.cors import CORSMiddleware
import os
from redis.commands.search.field import TextField, NumericField
from redis.commands.search.index_definition import IndexDefinition, IndexType

from songbirdapi.dependencies import load_settings

from .dbclient import RedisClient

from .routers import properties, downloads, songs, auth
from .version import version
from .settings import SongbirdServerConfig

app = FastAPI(
    dependencies=[
        Depends(auth.handle_api_key)
    ]
)

# TODO: cors configuration
origins = [
    "*"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.include_router(properties.router)
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
        TextField(f"$.{settings.redis_song_index_prefix}.trackName", as_name="trackName"),
        TextField(f"$.{settings.redis_song_index_prefix}.artistName", as_name="artistName"),
        TextField(f"$.{settings.redis_song_index_prefix}.collectionName", as_name="collectionName"),
        TextField(f"$.{settings.redis_song_index_prefix}.artworkUrl100", as_name="artworkUrl100"),
        TextField(f"$.{settings.redis_song_index_prefix}.primaryGenreName", as_name="primaryGenreName"),
        NumericField(f"$.{settings.redis_song_index_prefix}.trackNumber", as_name="trackNumber"),
        NumericField(f"$.{settings.redis_song_index_prefix}.trackCount", as_name="trackCount"),
        TextField(f"$.{settings.redis_song_index_prefix}.collectionArtistName", as_name="collectionArtistName"),
        NumericField(f"$.{settings.redis_song_index_prefix}.discNumber", as_name="discNumber"),
        NumericField(f"$.{settings.redis_song_index_prefix}.discCount", as_name="discCount"),
        TextField(f"$.{settings.redis_song_index_prefix}.releaseDate", as_name="releaseDate"),
        TextField(f"$.{settings.redis_song_index_prefix}.releaseDateKey", as_name="releaseDateKey")
    )
    res = await db.list_indices()
    if res is not None and settings.redis_song_index_name not in res:
        res = await db.create_index(
            settings.redis_song_index_name,
            schema,
            definition=IndexDefinition(prefix=[f"{settings.redis_song_index_prefix}:"],
            index_type=IndexType.JSON)
        )
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
