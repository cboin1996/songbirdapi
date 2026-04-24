from .database import get_db as get_db
from .settings import SongbirdServerConfig


def process_song_url(url: str):
    return url.split("&list")[0]


def load_settings() -> SongbirdServerConfig:
    return SongbirdServerConfig()  # pyright: ignore
