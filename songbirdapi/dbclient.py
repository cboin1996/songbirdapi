from redis.asyncio import Redis
from typing import Optional, Type
from redis.commands.search.index_definition import IndexDefinition
from redis.commands.search.query import Query
from redis.commands.json.path import Path
import logging
from pydantic import BaseModel, ValidationError
from fastapi.logger import logger

uvicorn_logger = logging.getLogger("uvicorn.error")
logger.handlers = uvicorn_logger.handlers
logger.setLevel(uvicorn_logger.level)


class RedisClient:
    def __init__(self, host, port):
        self.client = Redis(host=host, port=port, decode_responses=True)

    async def create_index(self, name: str, schema, definition: IndexDefinition):
        return await self.client.ft(name).create_index(schema, definition=definition)

    async def list_indices(self):
        return await self.client.execute_command("FT._LIST")

    async def simple_search(self, index: str, query: str):
        return await self.client.ft(index).search(Query(query))

    async def index(self, prefix: str, key: str, value: dict):
        return await self.client.json().set(
            f"{prefix}:{key}", Path.root_path(), value
        )  # pyright: ignore
    
    async def index_get(self, prefix: str, key: str, model):
        res = await self.client.json().get(
            f"{prefix}:{key}"
        ) # pyright: ignore
        try:
            return model.model_validate(res)
        except ValidationError as e:
            logger.error(f"Could not validate model: {e}")
            return None

    async def hset(self, prefix: str, key: str, value: dict):
        return await self.client.hset(
            f"{prefix}:{key}", mapping=value
        )  # pyright: ignore

    async def delete(self, prefix: str, key: str):
        return await self.client.delete(f"{prefix}:{key}")  # pyright: ignore

    async def hgetall(self, prefix: str, key: str, model):
        val = await self.client.hgetall(f"{prefix}:{key}")  # pyright: ignore
        if not val:
            return None
        try:
            return model.model_validate(val)
        except ValidationError as e:
            logger.error(f"Could not validate model: {e}")
            return None

    async def sadd(self, prefix: str, key: str, value: str):
        return await self.client.sadd(f"{prefix}:{key}", value)  # pyright: ignore

    async def srem(self, prefix: str, key: str, value: str):
        return await self.client.srem(f"{prefix}:{key}", value)  # pyright: ignore

    async def smembers(self, prefix: str, key: str):
        return await self.client.smembers(f"{prefix}:{key}")  # pyright: ignore
