from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from . import indexes
from ..core.config import settings
import certifi


_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

async def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(settings.MONGODB_URI,   tls=True,tlsCAFile=certifi.where())
        _db = _client[settings.MONGODB_DB]
    return _db

async def init_indexes():
    db = await get_db()
    await indexes.ensure(db)
