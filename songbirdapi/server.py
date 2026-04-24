import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.logger import logger
from fastapi.middleware.cors import CORSMiddleware

from songbirdapi.dependencies import load_settings

from . import database
from .routers import auth, downloads, properties, songs
from .version import version

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    database.init_engine(settings.postgres_dsn)
    await database.create_schema()
    yield
    await database.dispose_engine()


app = FastAPI(lifespan=lifespan, dependencies=[Depends(auth.handle_api_key)])

# TODO: cors configuration
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(properties.router)
app.include_router(downloads.router)
app.include_router(songs.router)


@app.get("/")
async def root():
    return {f"message": f"welcome to songbirdapi {version}!"}
