"""Repository for `simulations` (generated HTML sim cache).

NOT tenant-scoped: keyed by `daily_id` (globally-unique ObjectId string), matching
the existing handlers' queries. Same documented exception as TranscriptRepository.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from .base import BaseRepository


class SimulationRepository(BaseRepository):
    collection = "simulations"

    def _scoped(self, query: Optional[Mapping[str, Any]] = None) -> dict:
        return dict(query or {})  # no tenant injection — see module docstring

    async def latest_for_daily(self, daily_id: str) -> Optional[dict]:
        rows = await self.find_many({"daily_id": daily_id}, sort=[("created_at", -1)], limit=1)
        return rows[0] if rows else None

    async def create(self, doc: dict):
        return await self.insert_one(doc)
