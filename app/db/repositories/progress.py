"""Progress repositories.

WARNING — two collections exist for progress and they are NOT the same thing:
  * `student_progress`        — written by quiz.py (per-daily completion + quiz scores)
  * `student_daily_progress`  — written by progress.py (activity tracking + total_score)
This duplication predates the repo layer. The repos below mirror reality rather
than silently merging them (that would be a data migration, decided separately).
"""
from __future__ import annotations

from typing import Optional

from .base import BaseRepository


class StudentProgressRepository(BaseRepository):
    """`student_progress` — quiz-completion progress (see quiz.py)."""
    collection = "student_progress"

    async def get(self, *, student_id: str, daily_id: str) -> Optional[dict]:
        return await self.find_one({"student_id": student_id, "daily_id": daily_id})

    async def upsert(self, *, student_id: str, daily_id: str, doc: dict) -> None:
        await self.update_one(
            {"student_id": student_id, "daily_id": daily_id},
            {"$set": doc},
            upsert=True,
        )


class StudentDailyProgressRepository(BaseRepository):
    """`student_daily_progress` — activity tracking + weekly rollups (see progress.py)."""
    collection = "student_daily_progress"

    async def get(self, *, student_id: str, daily_id: str) -> Optional[dict]:
        return await self.find_one({"student_id": student_id, "daily_id": daily_id})

    async def upsert(self, *, student_id: str, daily_id: str, doc: dict) -> None:
        await self.update_one(
            {"student_id": student_id, "daily_id": daily_id},
            {"$set": doc},
            upsert=True,
        )

    async def list_for_student(
        self, *, student_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> list:
        q: dict = {"student_id": student_id}
        if start_date or end_date:
            date_q: dict = {}
            if start_date:
                date_q["$gte"] = start_date
            if end_date:
                date_q["$lte"] = end_date
            q["date"] = date_q
        return await self.find_many(q, sort=[("date", -1)])

    async def weekly_rollup(self, *, student_id: str, start_date: str) -> list:
        return await self.aggregate([
            {"$match": {"student_id": student_id, "date": {"$gte": start_date}}},
            {"$group": {
                "_id": "$date",
                "total_classes": {"$sum": 1},
                "completed_classes": {"$sum": {"$cond": ["$is_complete", 1, 0]}},
                "avg_completion": {"$avg": "$total_score"},
            }},
            {"$sort": {"_id": 1}},
        ])
