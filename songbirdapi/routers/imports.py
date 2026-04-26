import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from songbirdcore import itunes

from .. import crud
from ..dependencies import get_current_user, get_db, load_settings
from ..models import Song, User

_config = load_settings()
router = APIRouter(prefix="/import", tags=["import"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def import_song(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".mp3", ".m4a"):
        raise HTTPException(status_code=400, detail="only mp3 and m4a supported")

    new_uuid = str(uuid.uuid4())
    dest_path = os.path.join(_config.downloads_dir, f"{new_uuid}{ext}")

    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    props = None
    try:
        if ext == ".mp3":
            model = itunes.mp3_tag_reader(dest_path)
        else:
            model = itunes.m4a_tag_reader(dest_path)
        if model:
            props = model.model_dump()
    except Exception:
        pass

    song = Song(
        uuid=new_uuid,
        url="",
        file_path=dest_path,
        properties=props,
    )
    db.add(song)
    await db.commit()
    await crud.add_to_library(db, current_user.id, new_uuid)

    return {"song_id": new_uuid, "properties": props}
