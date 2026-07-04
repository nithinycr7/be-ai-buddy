"""
Daily Quiz API — HTTP layer only. All logic lives in DailyQuizService.
Handles auto-generation, student submission, XP/streak tracking.
"""
from fastapi import APIRouter, Depends
from typing import Dict, Any, Optional
from pydantic import BaseModel

from ..core.security import require_role, get_current_user, CurrentUser
from ..models.schemas import (
    Quiz, StreakTracking, QuizPublic,
    AnswerVerificationRequest, AnswerVerificationResponse,
)
from ..services.daily_quiz_service import DailyQuizService, get_daily_quiz_service

router = APIRouter(prefix="/daily-quiz", tags=["daily-quiz"], dependencies=[Depends(require_role("student", "parent", "teacher", "admin"))])


class GenerateQuizRequest(BaseModel):
    daily_id: str
    force_regenerate: bool = False


class SubmitQuizRequest(BaseModel):
    quiz_id: str
    daily_id: str
    student_id: str
    responses: Dict[str, Any]  # {qid: {answer, time_spent, hint_used}}
    time_taken_seconds: int


class QuizSubmissionResponse(BaseModel):
    attempt_id: str
    score: float
    correct_count: int
    total_questions: int
    xp_earned: int
    current_streak: int
    badges_earned: list[str] = []


@router.post("/generate", response_model=Quiz)
async def generate_daily_quiz(
    request: GenerateQuizRequest,
    service: DailyQuizService = Depends(get_daily_quiz_service),
    user: CurrentUser = Depends(require_role("teacher", "admin")),
):
    return await service.generate(daily_id=request.daily_id, force_regenerate=request.force_regenerate)


@router.get("/{daily_id}", response_model=QuizPublic)
async def get_daily_quiz(
    daily_id: str,
    student_id: Optional[str] = None,
    service: DailyQuizService = Depends(get_daily_quiz_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.get_for_daily(daily_id=daily_id, student_id=student_id, requester=user)


@router.post("/verify-answer", response_model=AnswerVerificationResponse)
async def verify_answer(
    request: AnswerVerificationRequest,
    service: DailyQuizService = Depends(get_daily_quiz_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.verify_answer(request, requester=user)


@router.post("/submit", response_model=QuizSubmissionResponse)
async def submit_daily_quiz(
    request: SubmitQuizRequest,
    service: DailyQuizService = Depends(get_daily_quiz_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.submit(
        quiz_id=request.quiz_id, daily_id=request.daily_id, student_id=request.student_id,
        responses=request.responses, time_taken_seconds=request.time_taken_seconds, requester=user,
    )


@router.get("/streak/{student_id}", response_model=StreakTracking)
async def get_student_streak(
    student_id: str,
    service: DailyQuizService = Depends(get_daily_quiz_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.get_streak(student_id=student_id, requester=user)
