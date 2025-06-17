import os
import sys
from pydantic_settings import BaseSettings
import sys
from typing import List


class SongbirdServerConfig(BaseSettings):
    """Configuration using .env file or defaults declared in here"""

    version: str = ""
    root_path: str = sys.path[0]
    downloads_dir: str = os.path.join(root_path, "downloads")
    dirs: List[str] = [downloads_dir]
    api_key: str
    redis_host: str = "localhost"
    redis_port: int = 6379

    class Config:
        config_path = os.path.join(os.path.dirname(sys.path[0]), f"{os.getenv("ENV", "")}.env")
        env_file = config_path
        env_file_encoding = "utf-8"
