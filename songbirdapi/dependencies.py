from functools import lru_cache
from .settings import SongbirdServerConfig
from .dbclient import RedisClient

def load_settings() -> SongbirdServerConfig:
    """Get dalle settings class"""
    return SongbirdServerConfig() # pyright: ignore

async def load_redis(settings: SongbirdServerConfig) -> RedisClient:
    return RedisClient(
        host=SongbirdServerConfig.redis_host,
        port=SongbirdServerConfig.redis_port
    )
