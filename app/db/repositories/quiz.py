"""Repositories for the quiz data plane: quizzes, quiz_responses, attempts.

Note: there are historically three quiz routers (quiz/quizzes/daily_quiz) with
overlapping grading. These repos give them a shared data layer; consolidating the
grading logic into a quiz_service is a separate, larger follow-up.
"""
from __future__ import annotations

from typing import Optional

from .base import BaseRepository


class QuizRepository(BaseRepository):
    collection = "quizzes"

    async def get(self, quiz_id: str) -> Optional[dict]:
        return await self.find_by_id(quiz_id)

    async def get_by_daily(self, daily_id: str) -> Optional[dict]:
        return await self.find_one({"daily_id": daily_id})


class QuizResponseRepository(BaseRepository):
    collection = "quiz_responses"

    async def next_attempt_number(self, *, daily_id: str, student_id: str) -> int:
        """1 for the first attempt, else previous max + 1."""
        latest = await self.find_many(
            {"daily_id": daily_id, "student_id": student_id},
            sort=[("attempt_number", -1)],
            limit=1,
        )
        return (latest[0]["attempt_number"] + 1) if latest else 1

    async def list_for_student(self, *, daily_id: str, student_id: str) -> list:
        return await self.find_many(
            {"daily_id": daily_id, "student_id": student_id},
            sort=[("attempt_number", 1)],
        )


class QuizAttemptRepository(BaseRepository):
    collection = "student_quiz_attempts"

    async def latest_completed(self, *, quiz_id: str, student_id: str) -> Optional[dict]:
        rows = await self.find_many(
            {"quiz_id": quiz_id, "student_id": student_id, "completed_at": {"$ne": None}},
            sort=[("completed_at", -1)],
            limit=1,
        )
        return rows[0] if rows else None
