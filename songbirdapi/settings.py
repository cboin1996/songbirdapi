import os
import sys
from datetime import datetime
from typing import List, Optional

import pydantic
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
import sys


class SongbirdServerConfig(BaseSettings):
    """Configuration using .env file or defaults declared in here"""

    version: str = ""
    run_local: bool = False
    root_path: str = sys.path[0]

    class Config:
        config_path = os.path.join(os.path.dirname(sys.path[0]), ".env")
        env_file = config_path
        env_file_encoding = "utf-8"
