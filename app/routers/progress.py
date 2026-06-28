from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from typing import Optional, List
from ..core.security import get_tenant, require_role, get_current_user, CurrentUser, assert_can_access_student
from ..db.repositories import (
    DailyClassRepository, get_daily_repo,
    StudentDailyProgressRepository, get_daily_progress_repo,
)
from ..db.repositories.base import InvalidObjectId
from ..models.schemas import StudentDailyProgress
from pydantic import BaseModel

router = APIRouter(prefix="/progress", tags=["progress"], dependencies=[Depends(require_role("student", "parent", "teacher", "admin"))])

class TrackActivityRequest(BaseModel):
    student_id: str
    daily_id: str
    activity: str  # "summary_viewed" or "story_generated"
    story_id: Optional[str] = None


def calculate_total_score(progress_doc: dict) -> float:
    """Calculate total score based on activities."""
    score = 0.0
    if progress_doc.get("summary_viewed"):
        score += 10.0   # Summary: 10%
    if progress_doc.get("story_generated"):
        score += 10.0   # Story: 10%
    score += progress_doc.get("quiz_score", 0.0)  # Quiz: up to 80% (already stored)
    return min(score, 100.0)

@router.post("/track")
async def track_activity(
    request: TrackActivityRequest,
    daily: DailyClassRepository = Depends(get_daily_repo),
    progress_repo: StudentDailyProgressRepository = Depends(get_daily_progress_repo),
    user: CurrentUser = Depends(get_current_user),
):
    """Track student activity (summary viewed or story generated)."""
    assert_can_access_student(user, request.student_id)

    try:
        daily_class = await daily.get(request.daily_id)
    except InvalidObjectId:
        raise HTTPException(status_code=400, detail="Invalid daily_id")
    if not daily_class:
        raise HTTPException(status_code=404, detail="Daily class not found")

    progress = await progress_repo.get(student_id=request.student_id, daily_id=request.daily_id)
    now = datetime.utcnow().isoformat()

    if not progress:
        progress = {
            "student_id": request.student_id,
            "daily_id": request.daily_id,
            "school_id": daily_class.get("school_id"),
            "date": daily_class.get("date"),
            "summary_viewed": False,
            "story_generated": False,
            "quiz_score": 0.0,
            "quiz_attempts": 0,
            "total_score": 0.0,
            "is_complete": False,
            "created_at": now,
            "updated_at": now,
        }

    update_fields = {"updated_at": now}
    if request.activity == "summary_viewed":
        update_fields["summary_viewed"] = True
        progress["summary_viewed"] = True
    elif request.activity == "story_generated":
        update_fields["story_generated"] = True
        progress["story_generated"] = True
    else:
        raise HTTPException(status_code=400, detail="Invalid activity type")

    new_total = calculate_total_score(progress)
    progress["total_score"] = new_total
    update_fields["total_score"] = new_total

    await progress_repo.update_one(
        {"student_id": request.student_id, "daily_id": request.daily_id},
        {"$set": update_fields, "$setOnInsert": {
            k: v for k, v in progress.items() if k not in update_fields and k != "total_score"
        }},
        upsert=True,
    )

    if "_id" in progress:
        progress["id"] = str(progress["_id"])
        del progress["_id"]
    return progress

@router.get("", response_model=List[StudentDailyProgress])
async def get_progress(
    student_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    progress_repo: StudentDailyProgressRepository = Depends(get_daily_progress_repo),
    user: CurrentUser = Depends(get_current_user),
):
    """Get student progress for a date range."""
    assert_can_access_student(user, student_id)
    docs = await progress_repo.list_for_student(
        student_id=student_id, start_date=start_date, end_date=end_date
    )
    results = []
    for doc in docs:
        if "_id" in doc:
            doc["id"] = str(doc["_id"])
            del doc["_id"]
        results.append(StudentDailyProgress(**doc))
    return results

@router.get("/weekly")
async def get_weekly_summary(
    student_id: str,
    start_date: str,  # YYYY-MM-DD
    progress_repo: StudentDailyProgressRepository = Depends(get_daily_progress_repo),
    user: CurrentUser = Depends(get_current_user),
):
    """Get weekly progress summary."""
    assert_can_access_student(user, student_id)
    rows = await progress_repo.weekly_rollup(student_id=student_id, start_date=start_date)
    return [
        {
            "date": doc["_id"],
            "total_classes": doc["total_classes"],
            "completed_classes": doc["completed_classes"],
            "avg_completion": round(doc["avg_completion"], 2),
        }
        for doc in rows
    ]
