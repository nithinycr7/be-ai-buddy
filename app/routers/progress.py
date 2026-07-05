from __future__ import annotations
from fastapi import APIRouter, Depends
from typing import Optional, List
from ..core.security import require_role, get_current_user, CurrentUser
from ..services.progress_service import ProgressService, get_progress_service
from ..models.schemas import StudentDailyProgress
from pydantic import BaseModel

router = APIRouter(prefix="/progress", tags=["progress"], dependencies=[Depends(require_role("student", "parent", "teacher", "admin"))])

class TrackActivityRequest(BaseModel):
    student_id: str
    daily_id: str
    activity: str  # "summary_viewed" or "story_generated"
    story_id: Optional[str] = None

@router.post("/track")
async def track_activity(
    request: TrackActivityRequest,
    service: ProgressService = Depends(get_progress_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.track_activity(
        student_id=request.student_id, daily_id=request.daily_id,
        activity=request.activity, requester=user,
    )

@router.get("", response_model=List[StudentDailyProgress])
async def get_progress(
    student_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    service: ProgressService = Depends(get_progress_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.list_progress(
        student_id=student_id, start_date=start_date, end_date=end_date, requester=user,
    )

@router.get("/weak-topics")
async def get_weak_topics(
    student_id: str,
    limit: int = 3,
    service: ProgressService = Depends(get_progress_service),
    user: CurrentUser = Depends(get_current_user),
):
    """Weakest-first list of attempted topics, for the home 'continue' card."""
    return await service.weak_topics(student_id=student_id, limit=limit, requester=user)

@router.get("/weekly")
async def get_weekly_summary(
    student_id: str,
    start_date: str,  # YYYY-MM-DD
    service: ProgressService = Depends(get_progress_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.weekly_summary(student_id=student_id, start_date=start_date, requester=user)
