from __future__ import annotations
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from . import indexes
from ..core.config import settings
import certifi


_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    """Sync accessor for the shared Motor client singleton (used by workers /
    services that need cross-database access, e.g. the transcripts DB)."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGODB_URI, tls=True, tlsCAFile=certifi.where())
    return _client


async def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        _client = get_client()
        _db = _client[settings.MONGODB_DB]
    return _db

async def init_indexes():
    db = await get_db()
    await indexes.ensure(db)


def close_client() -> None:
    """Close the shared Motor client (called on app shutdown from the lifespan)."""
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
