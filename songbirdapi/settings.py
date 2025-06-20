import os
import sys
from pydantic_settings import BaseSettings
import sys
from typing import List


class SongbirdServerConfig(BaseSettings):
    """Configuration using .env file or defaults declared in here"""

    version: str = ""
    root_path: str = sys.path[0]
    downloads_dir: str = os.path.join(root_path, "data", "downloads")
    dirs: List[str] = [downloads_dir]
    api_key: str
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_song_index_name: str = "idx:songs"
    redis_song_index_prefix: str = "properties"
    redis_song_url_prefix: str = "song-url"
    redis_song_id_prefix: str = "song-id"

    class Config:
        config_path = os.path.join(os.path.dirname(sys.path[0]), f"{os.getenv("ENV", "")}.env")
        env_file = config_path
        env_file_encoding = "utf-8"
