"""Repository for `students` — roster + per-student story persona."""
from __future__ import annotations

from typing import Optional

from .base import BaseRepository


class StudentRepository(BaseRepository):
    collection = "students"

    async def get(self, student_id: str) -> Optional[dict]:
        return await self.find_one({"student_id": student_id})

    async def exists(self, student_id: str) -> bool:
        return await self.find_one({"student_id": student_id}) is not None

    async def list(self, *, skip: int = 0, limit: int = 50) -> list:
        return await self.find_many({}, skip=skip, limit=limit)

    async def find_by_ids(self, sids: list) -> list:
        """Resolve student docs by a mix of external student_id and (24-char) _id."""
        oid_candidates = [s for s in sids if len(str(s)) == 24]
        return await self.find_many({"$or": [
            {"student_id": {"$in": sids}},
            {"_id": {"$in": oid_candidates}},
        ]}, limit=300)

    async def set_persona(self, student_id: str, persona: dict) -> None:
        await self.update_one({"student_id": student_id}, {"$set": {"story_persona": persona}})
