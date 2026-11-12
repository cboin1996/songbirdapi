import logging
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.logger import logger
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from songbirdapi.dependencies import load_settings

from . import database, security
from .models import ErrorLog
from .routers import (
    admin,
    auth,
    downloads,
    edit,
    imports,
    library,
    offline,
    player,
    playlists,
    properties,
    settings,
    share,
    songs,
)
from .routers import version as version_router
from .version import version

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)

_settings = load_settings()


async def _prune_sessions_at_startup():
    """Log the session settings, then delete dead sessions of every user, so
    users who never log in again don't keep their rows forever. A failure
    here never stops the API from starting."""
    s = _settings
    uvicorn_logger.info(
        "sessions: idle=%sd absolute=%sd replay_window=%ss max_per_user=%s "
        "reuse_detection=%s cookie_secure=%s",
        s.session_idle_days,
        s.session_absolute_days,
        s.refresh_replay_window_seconds,
        s.session_max_per_user,
        s.refresh_reuse_detection,
        s.cookie_secure,
    )
    try:
        async with database._session_factory() as db:
            pruned = await auth.prune_dead_sessions(db, security.utcnow(), s)
            await db.commit()
        uvicorn_logger.info("sessions: pruned %s dead sessions", pruned)
    except Exception:
        uvicorn_logger.exception("sessions: startup prune failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_engine(_settings.postgres_dsn)
    await database.create_schema()
    await database.seed_admin(
        _settings.admin_username, _settings.admin_email, _settings.admin_password
    )
    await _prune_sessions_at_startup()
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
app.include_router(offline.router, prefix=_V1)
app.include_router(library.router, prefix=_V1)
app.include_router(player.router, prefix=_V1)
app.include_router(properties.router, prefix=_V1)
app.include_router(downloads.router, prefix=_V1)
app.include_router(songs.router, prefix=_V1)
app.include_router(share.router, prefix=_V1)
app.include_router(edit.router, prefix=_V1)
app.include_router(imports.router, prefix=_V1)
app.include_router(playlists.router, prefix=_V1)
app.include_router(settings.router, prefix=_V1)
app.include_router(version_router.router, prefix=_V1)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    async with database.session_scope() as session:
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
