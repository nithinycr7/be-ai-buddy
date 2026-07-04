from fastapi import APIRouter, Depends, Query
from typing import Optional
from ..core.security import require_role
from ..services.leaderboard_service import (
    LeaderboardService, LeaderboardResponse, get_leaderboard_service,
)

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"], dependencies=[Depends(require_role("student", "parent", "teacher", "admin"))])


@router.get("", response_model=LeaderboardResponse)
async def get_leaderboard(
    current_student_id: str,
    period: str = Query("weekly", enum=["weekly", "all_time"]),
    school_id: Optional[str] = None,
    service: LeaderboardService = Depends(get_leaderboard_service),
):
    """Leaderboard: Top 5 + current user's rank, scoped to tenant (+ optional school)."""
    return await service.get(current_student_id=current_student_id, period=period, school_id=school_id)
