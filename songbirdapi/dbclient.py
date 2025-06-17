from redis.asyncio import Redis

"""
JSON examples from redis-py "home" page"
 https://redis-py.readthedocs.io/en/latest/examples/search_json_examples.html
"""

from typing import Optional, List
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query
import redis.exceptions
import logging
logger = logging.getLogger(__name__)

class RedisClient:
    def __init__(self, host, port):
        self.client = Redis(host=host,port=port)
 
    async def create_index(self, schema, definition: IndexDefinition):
        return await self.client.ft().create_index(schema, definition=definition)

    async def list_indices(self):
        return await self.client.execute_command("FT._LIST")
    
    async def search(self, query: Query):
        return await self.client.ft().search(query)
