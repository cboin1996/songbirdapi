import asyncio
import io
import os

from songbirdcore.itunes import artwork_searcher


def _fetch_and_store(
    itunes_url: str, thumb_path: str, full_path: str
) -> tuple[str | None, str | None]:
    response = artwork_searcher(itunes_url)
    if not response:
        return None, None
    data = response.content
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        full_img = img.copy()
        full_img.thumbnail((600, 600), Image.LANCZOS)
        full_img.save(full_path, "JPEG")
        thumb_img = img.copy()
        thumb_img.thumbnail((200, 200), Image.LANCZOS)
        thumb_img.save(thumb_path, "JPEG")
    except ImportError:
        with open(full_path, "wb") as f:
            f.write(data)
        with open(thumb_path, "wb") as f:
            f.write(data)
    return thumb_path, full_path


async def fetch_and_store_artwork(
    song_uuid: str, itunes_url: str, artwork_dir: str
) -> tuple[str | None, str | None]:
    song_dir = os.path.join(artwork_dir, song_uuid)
    os.makedirs(song_dir, exist_ok=True)
    thumb_path = os.path.join(song_dir, "thumb.jpg")
    full_path = os.path.join(song_dir, "full.jpg")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _fetch_and_store, itunes_url, thumb_path, full_path
    )


def copy_artwork(
    src_thumb: str | None, src_full: str | None, new_uuid: str, artwork_dir: str
) -> tuple[str | None, str | None]:
    """Copy a song's art files into the new song's own folder, so replacing the
    source's art later changes nothing behind the copy's (immutable) art URLs."""
    import shutil

    song_dir = os.path.join(artwork_dir, new_uuid)
    out: list[str | None] = []
    for src, name in ((src_thumb, "thumb.jpg"), (src_full, "full.jpg")):
        if src and os.path.exists(src):
            os.makedirs(song_dir, exist_ok=True)
            dst = os.path.join(song_dir, name)
            shutil.copyfile(src, dst)
            out.append(dst)
        else:
            out.append(src)
    return out[0], out[1]


async def store_artwork_from_bytes(
    song_uuid: str, data: bytes, artwork_dir: str
) -> tuple[str | None, str | None]:
    song_dir = os.path.join(artwork_dir, song_uuid)
    os.makedirs(song_dir, exist_ok=True)
    thumb_path = os.path.join(song_dir, "thumb.jpg")
    full_path = os.path.join(song_dir, "full.jpg")

    VALID_MAGIC = {
        b"\xff\xd8\xff": "jpeg",
        b"\x89PNG": "png",
        b"GIF8": "gif",
        b"RIFF": "webp",
    }
    if not any(data[: len(magic)] == magic for magic in VALID_MAGIC):
        raise ValueError("Unsupported image format")

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        full_img = img.copy()
        full_img.thumbnail((600, 600), Image.LANCZOS)
        full_img.save(full_path, "JPEG")
        thumb_img = img.copy()
        thumb_img.thumbnail((200, 200), Image.LANCZOS)
        thumb_img.save(thumb_path, "JPEG")
    except ImportError:
        with open(full_path, "wb") as f:
            f.write(data)
        with open(thumb_path, "wb") as f:
            f.write(data)

    return thumb_path, full_path
