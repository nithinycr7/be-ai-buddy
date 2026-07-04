"""Teacher quiz business logic. router → TeacherQuizService → (ManualQuizService + QuizRepository)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import Depends

from ...core.exceptions import AppError
from ...db.mongo import get_db
from ...db.repositories import QuizRepository, get_quiz_repo
from ...services.manual_quiz_service import ManualQuizService


class TeacherQuizService:
    def __init__(self, db, quizzes: QuizRepository):
        self.db = db
        self.quizzes = quizzes

    async def create_custom(self, data: dict) -> dict:
        data["tenant"] = self.quizzes.tenant  # header/token tenant wins over any body value
        try:
            return await ManualQuizService(self.db).create_and_save_quiz(data)
        except Exception as e:
            raise AppError(str(e))

    async def list(self, *, class_no: Optional[int], subject: Optional[str], limit: int) -> List[dict]:
        docs = await self.quizzes.list_recent(class_no=class_no, subject=subject, limit=limit)
        results = []
        for q in docs:
            q["id"] = str(q["_id"])
            q.pop("_id", None)
            if "daily_id" in q and hasattr(q["daily_id"], "__str__"):
                q["daily_id"] = str(q["daily_id"])
            results.append(q)
        return results


def get_teacher_quiz_service(
    quizzes: QuizRepository = Depends(get_quiz_repo),
    db=Depends(get_db),  # DI wiring for the ManualQuizService engine
) -> TeacherQuizService:
    return TeacherQuizService(db, quizzes)
