import asyncio
import os
import re
import urllib.request


def _rewrite_url(itunes_url: str, size: int) -> str:
    return re.sub(r'\d+x\d+bb', f'{size}x{size}bb', itunes_url)


def _download(url: str, path: str) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            with open(path, 'wb') as f:
                f.write(resp.read())
        return path
    except Exception:
        return None


async def fetch_and_store_artwork(song_uuid: str, itunes_url: str, artwork_dir: str) -> tuple[str | None, str | None]:
    song_dir = os.path.join(artwork_dir, song_uuid)
    os.makedirs(song_dir, exist_ok=True)

    thumb_path = os.path.join(song_dir, 'thumb.jpg')
    full_path = os.path.join(song_dir, 'full.jpg')

    loop = asyncio.get_event_loop()
    thumb = await loop.run_in_executor(None, _download, _rewrite_url(itunes_url, 300), thumb_path)
    full = await loop.run_in_executor(None, _download, _rewrite_url(itunes_url, 600), full_path)
    return thumb, full
