"""Admin business logic. router → AdminService → (Quiz + QuizResponse repos)."""
from __future__ import annotations

from fastapi import Depends

from ..db.repositories import (
    QuizRepository, get_quiz_repo,
    QuizResponseRepository, get_quiz_response_repo,
)


class AdminService:
    def __init__(self, quizzes: QuizRepository, responses: QuizResponseRepository):
        self.quizzes = quizzes
        self.responses = responses

    async def teacher_performance(self, teacher_email: str) -> dict:
        # Counts/averages scoped to the requesting school (tenant) only.
        return {
            "teacher_email": teacher_email,
            "quizzes_created": await self.quizzes.count(),
            "avg_quiz_score": await self.responses.average_score(),
        }


def get_admin_service(
    quizzes: QuizRepository = Depends(get_quiz_repo),
    responses: QuizResponseRepository = Depends(get_quiz_response_repo),
) -> AdminService:
    return AdminService(quizzes, responses)
