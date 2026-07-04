"""Leaderboard aggregations over `student_daily_progress` (tenant-scoped)."""
from __future__ import annotations

from typing import Optional

from .base import BaseRepository

_GROUP_XP = {"$group": {"_id": "$student_id", "total_xp": {"$sum": "$total_score"}}}


class LeaderboardRepository(BaseRepository):
    collection = "student_daily_progress"

    async def top_scores(self, *, filters: dict, limit: int) -> list:
        return await self.aggregate([
            {"$match": filters},
            _GROUP_XP,
            {"$sort": {"total_xp": -1}},
            {"$limit": limit},
            {"$lookup": {"from": "students", "localField": "_id",
                         "foreignField": "student_id", "as": "student_info"}},
            {"$unwind": {"path": "$student_info", "preserveNullAndEmptyArrays": True}},
            {"$project": {"student_id": "$_id", "xp": "$total_xp",
                          "first_name": "$student_info.first_name",
                          "last_name": "$student_info.last_name",
                          "avatar": "$student_info.avatar", "_id": 0}},
        ])

    async def user_total_xp(self, *, filters: dict, student_id: str) -> Optional[float]:
        rows = await self.aggregate([
            {"$match": {**filters, "student_id": student_id}},
            _GROUP_XP,
        ])
        return rows[0]["total_xp"] if rows else None

    async def count_higher(self, *, filters: dict, user_xp: float) -> int:
        rows = await self.aggregate([
            {"$match": filters},
            _GROUP_XP,
            {"$match": {"total_xp": {"$gt": user_xp}}},
            {"$count": "n"},
        ])
        return rows[0]["n"] if rows else 0
