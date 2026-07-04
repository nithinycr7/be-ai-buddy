"""Repository for `student_interventions` — the adaptive-intervention records."""
from __future__ import annotations

from typing import Optional

from .base import BaseRepository


class InterventionRepository(BaseRepository):
    collection = "student_interventions"

    async def find_existing(self, *, student_id: str, daily_id: str, quiz_id: str) -> Optional[dict]:
        return await self.find_one(
            {"student_id": student_id, "daily_id": daily_id, "quiz_id": quiz_id}
        )

    async def get(self, intervention_id: str) -> Optional[dict]:
        return await self.find_by_id(intervention_id)

    async def list_for_class(self, *, date: str, class_no=None, section=None, subject=None) -> list:
        q: dict = {"date": date}
        if class_no:
            q["class_no"] = class_no
        if section:
            q["section"] = section
        if subject:
            q["subject"] = subject
        return await self.find_many(q, limit=300)

    async def upsert_by_keys(self, *, student_id: str, daily_id: str, quiz_id: str, doc: dict):
        return await self.update_one(
            {"student_id": student_id, "daily_id": daily_id, "quiz_id": quiz_id},
            {"$set": doc},
            upsert=True,
        )
