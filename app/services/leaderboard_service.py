"""Leaderboard business logic. router → LeaderboardService → (Leaderboard + Student repos)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import Depends
from pydantic import BaseModel

from ..db.repositories import (
    LeaderboardRepository, get_leaderboard_repo,
    StudentRepository, get_student_repo,
)


class LeaderboardEntry(BaseModel):
    rank: int
    student_id: str
    name: str = "Unknown"
    avatar: Optional[str] = None
    xp: float


class LeaderboardResponse(BaseModel):
    top_5: List[LeaderboardEntry]
    user_rank: Optional[LeaderboardEntry] = None


def _full_name(doc: dict, default: str) -> str:
    return f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip() or default


class LeaderboardService:
    def __init__(self, repo: LeaderboardRepository, students: StudentRepository):
        self.repo = repo
        self.students = students

    async def get(self, *, current_student_id: str, period: str,
                  school_id: Optional[str]) -> LeaderboardResponse:
        filters: dict = {}
        if school_id:
            filters["school_id"] = school_id
        if period == "weekly":
            today = datetime.utcnow().date()
            start_of_week = today - timedelta(days=today.weekday())
            filters["date"] = {"$gte": start_of_week.isoformat()}

        top = await self.repo.top_scores(filters=filters, limit=5)
        top_5 = [
            LeaderboardEntry(rank=i, student_id=d["student_id"],
                             name=_full_name(d, "Student"), avatar=d.get("avatar"), xp=d["xp"])
            for i, d in enumerate(top, start=1)
        ]

        user_entry = None
        if current_student_id:
            user_xp = await self.repo.user_total_xp(filters=filters, student_id=current_student_id)
            if user_xp is not None:
                rank = await self.repo.count_higher(filters=filters, user_xp=user_xp) + 1
                sdoc = await self.students.get(current_student_id)
                name = _full_name(sdoc, "Me") if sdoc else "Me"
                avatar = sdoc.get("avatar") if sdoc else None
                user_entry = LeaderboardEntry(rank=rank, student_id=current_student_id,
                                              name=name, avatar=avatar, xp=user_xp)
            else:
                user_entry = LeaderboardEntry(rank=0, student_id=current_student_id, name="Me", xp=0)

        return LeaderboardResponse(top_5=top_5, user_rank=user_entry)


def get_leaderboard_service(
    repo: LeaderboardRepository = Depends(get_leaderboard_repo),
    students: StudentRepository = Depends(get_student_repo),
) -> LeaderboardService:
    return LeaderboardService(repo, students)
