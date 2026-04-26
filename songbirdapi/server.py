import logging
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.logger import logger
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from songbirdapi.dependencies import load_settings

from . import database
from .models import ErrorLog
from .routers import admin, auth, downloads, edit, imports, library, player, properties, share, songs
from .routers import version as version_router
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

_V1 = "/v1"
app.include_router(auth.router, prefix=_V1)
app.include_router(admin.router, prefix=_V1)
app.include_router(library.router, prefix=_V1)
app.include_router(player.router, prefix=_V1)
app.include_router(properties.router, prefix=_V1)
app.include_router(downloads.router, prefix=_V1)
app.include_router(songs.router, prefix=_V1)
app.include_router(share.router, prefix=_V1)
app.include_router(edit.router, prefix=_V1)
app.include_router(imports.router, prefix=_V1)
app.include_router(version_router.router, prefix=_V1)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    async with database._session_factory() as session:
        row = ErrorLog(
            id=str(uuid.uuid4()),
            level="error",
            path=request.url.path,
            method=request.method,
            status_code=500,
            message=str(exc),
            detail=tb,
        )
        session.add(row)
        try:
            await session.commit()
        except Exception:
            pass
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/")
async def root():
    return {f"message": f"welcome to songbirdapi {version}!"}
