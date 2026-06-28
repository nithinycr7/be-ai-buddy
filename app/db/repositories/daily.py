"""Repository for `classes_daily` — the per-day class document the whole app hangs off."""
from __future__ import annotations

from typing import Optional

from .base import BaseRepository


class DailyClassRepository(BaseRepository):
    collection = "classes_daily"

    async def get(self, daily_id: str) -> Optional[dict]:
        """Tenant-scoped fetch by string id (raises InvalidObjectId on bad input)."""
        return await self.find_by_id(daily_id)

    async def list_for_class(
        self, *, class_no: int, section: str, subject: Optional[str] = None
    ) -> list:
        q: dict = {"class_no": class_no, "section": section}
        if subject:
            q["subject"] = subject
        return await self.find_many(q, sort=[("date", -1)])

    async def set_summary_blocks(self, daily_id: str, blocks: list) -> None:
        await self.update_one({"_id": self._oid(daily_id)}, {"$set": {"summary_blocks": blocks}})
