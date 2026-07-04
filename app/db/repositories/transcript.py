"""Repository for `transcripts`.

INTENTIONALLY NOT tenant-scoped: transcripts are keyed by `daily_id` (a globally
unique ObjectId string), and the existing handlers query them by daily_id alone.
Scoping by tenant here would silently change behavior, so `_scoped` is overridden
to a no-op. This is the documented exception to the tenant-always rule.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from .base import BaseRepository


class TranscriptRepository(BaseRepository):
    collection = "transcripts"

    def _scoped(self, query: Optional[Mapping[str, Any]] = None) -> dict:
        # Deliberately no tenant injection — see module docstring.
        return dict(query or {})

    async def get_for_daily(self, daily_id: str) -> Optional[dict]:
        return await self.find_one({"daily_id": daily_id})

    async def upsert_for_daily(self, daily_id: str, doc: dict):
        """Replace the transcript for a daily (keyed by daily_id; not tenant-scoped)."""
        return await self.c.replace_one(
            {"daily_id": daily_id}, {**doc, "daily_id": daily_id}, upsert=True)
