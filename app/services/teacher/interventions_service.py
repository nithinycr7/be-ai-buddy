"""Teacher intervention-insights business logic.
router → InterventionInsightsService → (Intervention + Student repos).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import Depends
from pydantic import BaseModel

from ...core.exceptions import AppError
from ...db.repositories import (
    InterventionRepository, get_intervention_repo,
    StudentRepository, get_student_repo,
)


class InterventionRow(BaseModel):
    id: str
    rollNo: str
    student: str
    topic: Optional[str] = None
    initial_score: float
    intervention_type: Optional[str] = None
    gap_concept: Optional[str] = None
    verification_score: Optional[float] = None
    learning_gain: Optional[float] = None
    status: str


class InterventionInsightsResponse(BaseModel):
    rows: List[InterventionRow]
    avg_learning_gain: float
    improved_count: int
    needs_support_count: int
    mastered_count: int
    total: int


class InterventionInsightsService:
    def __init__(self, interventions: InterventionRepository, students: StudentRepository):
        self.interventions = interventions
        self.students = students

    async def class_insights(self, *, class_no: Optional[int], section: Optional[str],
                             subject: Optional[str], date_str: str) -> InterventionInsightsResponse:
        try:
            records = await self.interventions.list_for_class(
                date=date_str, class_no=class_no, section=section, subject=subject)

            sids = list({r["student_id"] for r in records if "student_id" in r})
            students = await self.students.find_by_ids(sids)
            smap: dict = {}
            for s in students:
                if "student_id" in s:
                    smap[s["student_id"]] = s
                smap[str(s["_id"])] = s

            rows: List[InterventionRow] = []
            gains: List[float] = []
            improved = needs = mastered = 0

            for r in records:
                sid = r.get("student_id")
                student = smap.get(sid) or smap.get(str(sid))
                name = student.get("name", f"Student {sid}") if student else f"Student {sid}"
                roll = (student.get("roll_no") or student.get("student_id") or str(sid)) if student else str(sid)

                status = r.get("status", "pending")
                if status == "improved":
                    improved += 1
                elif status == "needs_teacher_support":
                    needs += 1
                elif status == "mastered":
                    mastered += 1

                gain = r.get("learning_gain")
                if gain is not None:
                    gains.append(gain)

                rows.append(InterventionRow(
                    id=str(r.get("_id")), rollNo=str(roll), student=name, topic=r.get("topic"),
                    initial_score=float(r.get("initial_score", 0.0)),
                    intervention_type=r.get("intervention_type"), gap_concept=r.get("gap_concept"),
                    verification_score=r.get("verification_score"), learning_gain=gain, status=status))

            rows.sort(key=lambda x: x.rollNo)
            avg_gain = round(sum(gains) / len(gains), 1) if gains else 0.0

            return InterventionInsightsResponse(
                rows=rows, avg_learning_gain=avg_gain, improved_count=improved,
                needs_support_count=needs, mastered_count=mastered, total=len(rows))
        except AppError:
            raise
        except Exception as e:
            raise AppError(str(e))


def get_intervention_insights_service(
    interventions: InterventionRepository = Depends(get_intervention_repo),
    students: StudentRepository = Depends(get_student_repo),
) -> InterventionInsightsService:
    return InterventionInsightsService(interventions, students)
