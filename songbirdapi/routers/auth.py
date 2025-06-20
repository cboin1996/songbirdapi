from fastapi import Depends, Security, HTTPException, status, Request
from fastapi.security import APIKeyHeader
from fastapi.logger import logger
import logging

from ..dependencies import load_settings
from songbirdapi.settings import SongbirdServerConfig

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)


api_key = APIKeyHeader(name="x-api-key")


async def handle_api_key(
    req: Request,
    key: str = Security(api_key),
    config: SongbirdServerConfig = Depends(load_settings),
):
    if key != config.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key"
        )
