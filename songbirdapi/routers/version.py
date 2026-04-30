from importlib.metadata import version, PackageNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db

router = APIRouter()


def _get_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


@router.get("/version")
async def get_version():
    return {
        "api_version": _get_version("songbirdapi"),
        "core_version": _get_version("songbirdcore"),
    }


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    # Verify the DB layer is actually responsive — a 200 from this endpoint
    # is meaningful for downstream readiness checks (CI deploy poll etc.).
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"db unhealthy: {exc!r}",
        )
    return {"status": "ok"}
