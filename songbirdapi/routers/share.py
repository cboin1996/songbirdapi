import mimetypes
import os
import re
from datetime import datetime, timezone
from typing import AsyncGenerator

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..dependencies import get_current_user, get_db
from ..models import User

router = APIRouter(prefix="/share", tags=["share"])


class ShareTokenResponse(BaseModel):
    token: str
    expires_at: str


class ShareInfoResponse(BaseModel):
    token: str
    expires_at: str
    song_id: str
    properties: dict | None


@router.post("/songs/{song_id}", response_model=ShareTokenResponse)
async def create_share_link(
    song_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    song = await crud.get_song(db, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    entry = await crud.create_share_token(db, song_id, current_user.id)
    return ShareTokenResponse(token=entry.token, expires_at=entry.expires_at.isoformat())


def _validate_token(entry, token: str):
    if not entry:
        raise HTTPException(status_code=404, detail="Share link not found or expired")
    if entry.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Share link has expired")


@router.get("/{token}/info", response_model=ShareInfoResponse)
async def get_share_info(token: str, db: AsyncSession = Depends(get_db)):
    entry = await crud.get_share_token(db, token)
    _validate_token(entry, token)
    song = await crud.get_song(db, entry.song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    return ShareInfoResponse(
        token=token,
        expires_at=entry.expires_at.isoformat(),
        song_id=song.uuid,
        properties=song.properties,
    )


@router.get("/{token}/download")
async def download_shared(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    entry = await crud.get_share_token(db, token)
    _validate_token(entry, token)
    song = await crud.get_song(db, entry.song_id)
    if not song or not os.path.exists(song.file_path):
        raise HTTPException(status_code=404, detail="Song not found")

    file_size = os.path.getsize(song.file_path)
    media_type = mimetypes.guess_type(song.file_path)[0] or "audio/mpeg"
    track_name = (song.properties or {}).get("trackName", "song")
    artist_name = (song.properties or {}).get("artistName", "")
    filename = f"{track_name} - {artist_name}.mp3".replace("/", "-")
    disposition = f'attachment; filename="{filename}"'
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(
            song.file_path,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes", "Content-Disposition": disposition},
        )

    match = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not match:
        raise HTTPException(status_code=416, detail="Invalid Range header")

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1

    if start >= file_size or end >= file_size or start > end:
        raise HTTPException(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
            detail="Range Not Satisfiable",
        )

    chunk_size = end - start + 1

    async def stream() -> AsyncGenerator[bytes, None]:
        async with await anyio.open_file(song.file_path, "rb") as f:
            await f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                data = await f.read(min(65536, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        stream(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
            "Content-Disposition": disposition,
        },
    )
