import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.logger import logger
from fastapi.middleware.cors import CORSMiddleware

from songbirdapi.dependencies import load_settings

from . import database
from .routers import admin, auth, downloads, library, properties, songs
from .version import version

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)

_settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_engine(_settings.postgres_dsn)
    await database.create_schema()
    await database.seed_admin(_settings.admin_username, _settings.admin_email, _settings.admin_password)
    yield
    await database.dispose_engine()


app = FastAPI(lifespan=lifespan)

origins = [o.strip() for o in _settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(library.router)
app.include_router(properties.router)
app.include_router(downloads.router)
app.include_router(songs.router)


@app.get("/")
async def root():
    return {f"message": f"welcome to songbirdapi {version}!"}
