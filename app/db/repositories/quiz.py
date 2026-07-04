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
        """Lookup where `daily_id` is stored as a plain string."""
        return await self.find_one({"daily_id": daily_id})

    async def get_by_daily_oid(self, daily_id: str) -> Optional[dict]:
        """Lookup where `daily_id` is stored as an ObjectId (the live daily-quiz shape,
        written by AutoQuizGenerator). Raises InvalidObjectId on malformed input."""
        return await self.find_one({"daily_id": self._oid(daily_id)})


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

    async def average_score(self) -> Optional[float]:
        rows = await self.aggregate([{"$group": {"_id": None, "avg": {"$avg": "$score"}}}])
        return rows[0]["avg"] if rows else None


class QuizAttemptRepository(BaseRepository):
    collection = "student_quiz_attempts"

    async def latest_completed(self, *, quiz_id: str, student_id: str) -> Optional[dict]:
        rows = await self.find_many(
            {"quiz_id": quiz_id, "student_id": student_id, "completed_at": {"$ne": None}},
            sort=[("completed_at", -1)],
            limit=1,
        )
        return rows[0] if rows else None

    async def get_active(self, *, quiz_id: str, student_id: str) -> Optional[dict]:
        """The in-progress (not yet completed) attempt, populated by verify-answer."""
        return await self.find_one(
            {"quiz_id": quiz_id, "student_id": student_id, "completed_at": None}
        )

    async def latest_for_daily(self, *, daily_id: str, student_id: str) -> Optional[dict]:
        rows = await self.find_many(
            {"daily_id": daily_id, "student_id": student_id},
            sort=[("attempt_number", -1)],
            limit=1,
        )
        return rows[0] if rows else None

    async def record_answer(self, *, daily_id: str, student_id: str,
                            set_fields: dict, insert_fields: dict):
        """Upsert the active attempt with one graded answer (verify-answer path)."""
        return await self.update_one(
            {"daily_id": daily_id, "student_id": student_id, "completed_at": None},
            {"$set": set_fields, "$setOnInsert": insert_fields},
            upsert=True,
        )

    async def finalize(self, attempt_oid, fields: dict):
        return await self.update_one({"_id": attempt_oid}, {"$set": fields})
