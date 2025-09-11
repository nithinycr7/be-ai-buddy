# routes/lesson_plan.py
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
from ...db.mongo import get_db
from app.services.teacher.lesson_plan import LessonPlanService
from pydantic import BaseModel,Field

router = APIRouter(prefix="/lesson-plans", tags=["Lesson Plans"])


class LessonPlanRequest(BaseModel):
    class_no: int
    subject: str
    chapter: str
    teacher: str
    section: str
    periods: int

@router.post("/generate")
async def generate_lesson_plan(
      request: LessonPlanRequest,
    db: AsyncIOMotorDatabase =  Depends(get_db)
):
    service = LessonPlanService(db)

    result = await service.generate_lesson_plan(
        class_no=request.class_no,
        subject=request.subject,
        chapter=request.chapter,
        teacher=request.teacher,
        section=request.section,
        periods=request.periods
    )
    return {
        "success": True,
        "from_db": result["from_db"],
        "lesson_plan": result["plan"],
        "timestamp": datetime.now(timezone.utc)
    }