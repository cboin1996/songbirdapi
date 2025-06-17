from valkey.asyncio import Valkey

"""
JSON examples from valkey-py "home" page"
 https://valkey-py.readthedocs.io/en/latest/examples/search_json_examples.html
"""

from typing import Optional
from valkey.commands.search.indexDefinition import IndexDefinition, IndexType
from valkey.commands.search.query import Query
import valkey.exceptions
import logging
logger = logging.getLogger(__name__)

class ValkeyClient:
    def __init__(self, host, port):
        self.client = Valkey(host=host,port=port)
 
    async def handle_result(self, response) -> bool:
        if "OK" not in response:
            logger.error(f"Received error from valkey: {response}")
            return False
        return True

    async def create_index(self, schema, definition: IndexDefinition):
        res = await self.client.ft().create_index(schema, definition=definition)
        return self.handle_result(res)

    async def search(self, query: Query):
        res = await self.client.ft().search(query)
        return self.handle_result(res)
