"""Progress business logic. router → ProgressService → (Daily + DailyProgress repos)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import Depends

from ..core.exceptions import BadRequestError, NotFoundError
from ..core.security import CurrentUser, assert_can_access_student
from ..db.repositories import (
    DailyClassRepository, get_daily_repo,
    StudentDailyProgressRepository, get_daily_progress_repo,
)
from ..db.repositories.base import InvalidObjectId
from ..models.schemas import StudentDailyProgress


def calculate_total_score(progress_doc: dict) -> float:
    """Summary 10% + Story 10% + Quiz (already stored, up to 80%), capped at 100."""
    score = 0.0
    if progress_doc.get("summary_viewed"):
        score += 10.0
    if progress_doc.get("story_generated"):
        score += 10.0
    score += progress_doc.get("quiz_score", 0.0)
    return min(score, 100.0)


def _to_model(doc: dict) -> StudentDailyProgress:
    if "_id" in doc:
        doc["id"] = str(doc["_id"])
        del doc["_id"]
    return StudentDailyProgress(**doc)


class ProgressService:
    def __init__(self, daily: DailyClassRepository, progress: StudentDailyProgressRepository):
        self.daily = daily
        self.progress = progress

    async def track_activity(self, *, student_id: str, daily_id: str, activity: str,
                             requester: CurrentUser) -> dict:
        assert_can_access_student(requester, student_id)

        try:
            daily_class = await self.daily.get(daily_id)
        except InvalidObjectId:
            raise BadRequestError("Invalid daily_id")
        if not daily_class:
            raise NotFoundError("Daily class not found")

        progress = await self.progress.get(student_id=student_id, daily_id=daily_id)
        now = datetime.utcnow().isoformat()

        if not progress:
            progress = {
                "student_id": student_id,
                "daily_id": daily_id,
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
        if activity == "summary_viewed":
            update_fields["summary_viewed"] = True
            progress["summary_viewed"] = True
        elif activity == "story_generated":
            update_fields["story_generated"] = True
            progress["story_generated"] = True
        else:
            raise BadRequestError("Invalid activity type")

        new_total = calculate_total_score(progress)
        progress["total_score"] = new_total
        update_fields["total_score"] = new_total

        await self.progress.update_one(
            {"student_id": student_id, "daily_id": daily_id},
            {"$set": update_fields, "$setOnInsert": {
                k: v for k, v in progress.items() if k not in update_fields and k != "total_score"
            }},
            upsert=True,
        )

        if "_id" in progress:
            progress["id"] = str(progress["_id"])
            del progress["_id"]
        return progress

    async def list_progress(self, *, student_id: str, start_date: Optional[str],
                            end_date: Optional[str], requester: CurrentUser) -> List[StudentDailyProgress]:
        assert_can_access_student(requester, student_id)
        docs = await self.progress.list_for_student(
            student_id=student_id, start_date=start_date, end_date=end_date
        )
        return [_to_model(d) for d in docs]

    async def weekly_summary(self, *, student_id: str, start_date: str,
                             requester: CurrentUser) -> List[dict]:
        assert_can_access_student(requester, student_id)
        rows = await self.progress.weekly_rollup(student_id=student_id, start_date=start_date)
        return [
            {
                "date": doc["_id"],
                "total_classes": doc["total_classes"],
                "completed_classes": doc["completed_classes"],
                "avg_completion": round(doc["avg_completion"], 2),
            }
            for doc in rows
        ]


def get_progress_service(
    daily: DailyClassRepository = Depends(get_daily_repo),
    progress: StudentDailyProgressRepository = Depends(get_daily_progress_repo),
) -> ProgressService:
    return ProgressService(daily, progress)
