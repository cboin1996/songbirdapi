from functools import lru_cache
from .settings import SongbirdServerConfig
from .dbclient import ValkeyClient

def load_settings() -> SongbirdServerConfig:
    """Get dalle settings class"""
    return SongbirdServerConfig() # pyright: ignore

async def load_valkey(settings: SongbirdServerConfig) -> ValkeyClient:
    return ValkeyClient(
        host=SongbirdServerConfig.valkey_host,
        port=SongbirdServerConfig.valkey_port
    )
