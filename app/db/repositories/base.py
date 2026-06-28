"""
Base repository — the single place Mongo access is allowed to live.

Every repository is constructed bound to a `(db, tenant)` pair, and every query
it runs is automatically tenant-scoped via `_scoped()`. This is the structural
fix for the class of bug where a hand-written handler forgot `"tenant": tenant`
in a filter and leaked another school's data. Routers should depend on a
repository (see `app/db/repositories/__init__.py` providers) and never call
`get_db()` or touch a collection directly.

Ownership (student/parent scoping) stays in the router via
`assert_can_access_student(user, student_id)` — that needs the CurrentUser and is
an auth concern; the repo only guarantees tenant isolation + data access.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase


class InvalidObjectId(ValueError):
    """Raised when a string id cannot be parsed as an ObjectId.

    Routers map this to HTTP 400 (it's malformed input, not a missing record)."""


class BaseRepository:
    """Tenant-scoped async data access for a single collection.

    Subclasses set ``collection``. All reads/writes go through helpers that
    inject ``{"tenant": self.tenant}`` so it can never be forgotten.
    """

    collection: str = ""

    def __init__(self, db: AsyncIOMotorDatabase, tenant: str):
        if not self.collection:
            raise NotImplementedError(f"{type(self).__name__} must set `collection`")
        self.db = db
        self.tenant = tenant
        self.c = db[self.collection]

    # ── scoping helpers ──────────────────────────────────────────────────────
    def _scoped(self, query: Optional[Mapping[str, Any]] = None) -> dict:
        """Return a shallow copy of ``query`` with the tenant filter forced on."""
        q = dict(query or {})
        q["tenant"] = self.tenant
        return q

    @staticmethod
    def _oid(id_str: str) -> ObjectId:
        try:
            return ObjectId(id_str)
        except (InvalidId, TypeError):
            raise InvalidObjectId(id_str)

    # ── reads ────────────────────────────────────────────────────────────────
    async def find_one(self, query: Optional[Mapping[str, Any]] = None, **kw):
        return await self.c.find_one(self._scoped(query), **kw)

    async def find_by_id(self, id_str: str, **kw):
        """Tenant-scoped lookup by string ``_id``. Raises InvalidObjectId on bad input."""
        return await self.find_one({"_id": self._oid(id_str)}, **kw)

    async def find_many(
        self,
        query: Optional[Mapping[str, Any]] = None,
        *,
        sort: Optional[Sequence] = None,
        skip: int = 0,
        limit: int = 0,
    ) -> list:
        cur = self.c.find(self._scoped(query))
        if sort:
            cur = cur.sort(sort)
        if skip:
            cur = cur.skip(skip)
        if limit:
            cur = cur.limit(limit)
        return await cur.to_list(length=(limit or None))

    async def count(self, query: Optional[Mapping[str, Any]] = None) -> int:
        return await self.c.count_documents(self._scoped(query))

    async def aggregate(self, pipeline: list) -> list:
        """Run an aggregation, defensively prepending a tenant ``$match`` so the
        pipeline is isolated even if the caller's first stage forgot it."""
        full = [{"$match": {"tenant": self.tenant}}, *pipeline]
        return [doc async for doc in self.c.aggregate(full)]

    # ── writes ───────────────────────────────────────────────────────────────
    async def insert_one(self, doc: Mapping[str, Any]):
        """Insert, forcing the tenant stamp onto the document."""
        return await self.c.insert_one(self._scoped(doc))

    async def update_one(
        self,
        query: Mapping[str, Any],
        update: Mapping[str, Any],
        *,
        upsert: bool = False,
    ):
        return await self.c.update_one(self._scoped(query), update, upsert=upsert)

    async def delete_one(self, query: Mapping[str, Any]):
        return await self.c.delete_one(self._scoped(query))
