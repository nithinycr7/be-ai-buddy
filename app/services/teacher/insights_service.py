"""Teacher class-insights business logic.
router → InsightsService → (StudentDailyProgress + Student repos).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import Depends
from pydantic import BaseModel

from ...core.exceptions import AppError
from ...db.repositories import (
    StudentDailyProgressRepository, get_daily_progress_repo,
    StudentRepository, get_student_repo,
)


class StudentInsight(BaseModel):
    id: str
    rollNo: str
    name: str
    score: float
    readSummary: bool
    readStory: bool
    status: str  # Excellent, Good, Average, Needs Attention


class InsightsResponse(BaseModel):
    distribution: List[dict]
    students: List[StudentInsight]
    class_average: float
    top_score: float


_EMPTY_DISTRIBUTION = [
    {"range": "0-40", "count": 0}, {"range": "40-60", "count": 0},
    {"range": "60-80", "count": 0}, {"range": "80-100", "count": 0},
]


class InsightsService:
    def __init__(self, progress: StudentDailyProgressRepository, students: StudentRepository):
        self.progress = progress
        self.students = students

    async def class_insights(self, *, class_no: Optional[int], section: Optional[str],
                             subject: Optional[str], date_str: str) -> InsightsResponse:
        try:
            query: dict = {"date": date_str}
            if class_no:
                query["class_no"] = class_no
            if section:
                query["section"] = section
            if subject:
                query["subject"] = subject

            progress_data = await self.progress.find_many(query, limit=100)
            if not progress_data:
                return InsightsResponse(distribution=[dict(d) for d in _EMPTY_DISTRIBUTION],
                                        students=[], class_average=0.0, top_score=0.0)

            sids = list({p["student_id"] for p in progress_data if "student_id" in p})
            students = await self.students.find_by_ids(sids)
            smap: dict = {}
            for s in students:
                if "student_id" in s:
                    smap[s["student_id"]] = s
                smap[str(s["_id"])] = s

            # Collapse to one row per student (keep highest quiz_latest_score; merge read flags)
            by_student: dict = {}
            for progress in progress_data:
                sid = progress.get("student_id")
                score = progress.get("quiz_latest_score", 0) or 0
                existing = by_student.get(sid)
                if existing is None or score > (existing.get("quiz_latest_score") or 0):
                    by_student[sid] = progress
                else:
                    existing["summary_viewed"] = existing.get("summary_viewed") or progress.get("summary_viewed", False)
                    existing["story_generated"] = existing.get("story_generated") or progress.get("story_generated", False)

            insight_students, scores = [], []
            for sid, progress in by_student.items():
                student = smap.get(sid) or smap.get(str(sid))
                student_name = student.get("name", "Unknown") if student else f"Student {sid}"
                roll_no = (student.get("roll_no") or student.get("student_id") or str(sid)) if student else str(sid)
                read_summary = progress.get("summary_viewed", False)
                read_story = progress.get("story_generated", False)

                quiz_score = 0
                if progress.get("quiz_taken"):
                    quiz_score = progress.get("quiz_latest_score", 0) or 0
                scores.append(quiz_score)

                status = "Needs Attention"
                if quiz_score >= 80:
                    status = "Excellent"
                elif quiz_score >= 60:
                    status = "Good"
                elif quiz_score >= 40:
                    status = "Average"

                insight_students.append(StudentInsight(
                    id=str(sid), rollNo=roll_no, name=student_name, score=quiz_score,
                    readSummary=read_summary, readStory=read_story, status=status))

            dist = {"0-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
            for s in scores:
                if s < 40:
                    dist["0-40"] += 1
                elif s < 60:
                    dist["40-60"] += 1
                elif s < 80:
                    dist["60-80"] += 1
                else:
                    dist["80-100"] += 1
            distribution = [{"range": k, "count": v} for k, v in dist.items()]

            class_avg = sum(scores) / len(scores) if scores else 0
            top_score = max(scores) if scores else 0
            insight_students.sort(key=lambda x: x.rollNo)

            return InsightsResponse(
                distribution=distribution, students=insight_students,
                class_average=round(class_avg, 1), top_score=round(top_score, 1))
        except AppError:
            raise
        except Exception as e:
            raise AppError(str(e))


def get_insights_service(
    progress: StudentDailyProgressRepository = Depends(get_daily_progress_repo),
    students: StudentRepository = Depends(get_student_repo),
) -> InsightsService:
    return InsightsService(progress, students)
