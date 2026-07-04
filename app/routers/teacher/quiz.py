from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional

from app.core.security import require_role
from app.services.teacher.quiz_service import TeacherQuizService, get_teacher_quiz_service

router = APIRouter(dependencies=[Depends(require_role("teacher", "admin"))])


class CustomQuizRequest(BaseModel):
    source: str = "custom"  # custom | textbook
    class_no: int
    subject: str
    board: str = "CBSE"
    difficulty: str = "medium"
    num_questions: int = 10
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    topics: List[str] = []
    tenant: str = "default"  # overridden by the request tenant
    teacher_id: Optional[str] = None


@router.post("/custom")
async def generate_custom_quiz(
    payload: CustomQuizRequest,
    service: TeacherQuizService = Depends(get_teacher_quiz_service),
):
    return await service.create_custom(payload.dict())


@router.get("/", response_model=List[dict])
async def list_quizzes(
    class_no: Optional[int] = None,
    subject: Optional[str] = None,
    limit: int = 50,
    service: TeacherQuizService = Depends(get_teacher_quiz_service),
):
    return await service.list(class_no=class_no, subject=subject, limit=limit)
