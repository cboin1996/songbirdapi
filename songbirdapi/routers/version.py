from importlib.metadata import version, PackageNotFoundError

from fastapi import APIRouter

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
async def health():
    return {"status": "ok"}
