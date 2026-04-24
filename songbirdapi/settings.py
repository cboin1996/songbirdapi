import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import List

_PROJECT_ROOT = Path(__file__).parent.parent


class SongbirdServerConfig(BaseSettings):
    """Configuration using .env file or defaults declared in here"""

    version: str = ""
    root_path: str = sys.path[0]
    downloads_dir: str = os.path.join(root_path, "data", "downloads")
    dirs: List[str] = [downloads_dir]
    api_key: str
    jwt_secret: str
    cors_origins: str = "http://localhost:3000"
    admin_username: str = ""
    admin_email: str = ""
    admin_password: str = ""
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "songbirdapi"
    postgres_user: str = "songbirdapi"
    postgres_password: str

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = str(_PROJECT_ROOT / f"{os.getenv('ENV', '')}.env")
        env_file_encoding = "utf-8"
