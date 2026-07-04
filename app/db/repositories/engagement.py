"""Gamification/engagement repositories: streak tracking + quiz analytics."""
from __future__ import annotations

from typing import Optional

from .base import BaseRepository


class StreakRepository(BaseRepository):
    collection = "streak_tracking"

    async def get(self, student_id: str) -> Optional[dict]:
        return await self.find_one({"student_id": student_id})

    async def upsert(self, student_id: str, doc: dict) -> None:
        await self.update_one({"student_id": student_id}, {"$set": doc}, upsert=True)


class QuizAnalyticsRepository(BaseRepository):
    collection = "quiz_analytics"

    async def bump(self, *, quiz_id: str, question_id: str, is_correct: bool,
                   hint_used: bool, time_spent) -> None:
        """Per-question rolling counters + time samples (one call per answered question)."""
        await self.update_one(
            {"quiz_id": quiz_id, "question_id": question_id},
            {
                "$inc": {
                    "total_attempts": 1,
                    "correct_count": 1 if is_correct else 0,
                    "hint_usage_count": 1 if hint_used else 0,
                },
                "$push": {"time_samples": time_spent},
            },
            upsert=True,
        )
