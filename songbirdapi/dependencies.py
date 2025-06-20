from functools import lru_cache
from .settings import SongbirdServerConfig
from .dbclient import RedisClient


def process_song_url(url: str):
    return url.split("&list")[0]


def load_settings() -> SongbirdServerConfig:
    """Get dalle settings class"""
    return SongbirdServerConfig()  # pyright: ignore


def load_redis(settings: SongbirdServerConfig) -> RedisClient:
    return RedisClient(host=settings.redis_host, port=settings.redis_port)
