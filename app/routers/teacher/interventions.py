"""
Teacher-facing intervention insights.
Read-only. Aggregates `student_interventions` for a class/section/subject/date
into the "Learning Gain / Understood After Support" table the dashboard shows.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.mongo import get_db
from app.core.security import get_tenant, require_role

router = APIRouter(dependencies=[Depends(require_role("teacher", "admin"))])


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
    status: str  # mastered | improved | needs_teacher_support | pending | skipped


class InterventionInsightsResponse(BaseModel):
    rows: List[InterventionRow]
    avg_learning_gain: float
    improved_count: int
    needs_support_count: int
    mastered_count: int
    total: int


@router.get("", response_model=InterventionInsightsResponse)
async def get_intervention_insights(
    class_no: Optional[int] = Query(None),
    section: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    date_str: str = Query(..., alias="date", description="Date YYYY-MM-DD"),
    tenant: str = Depends(get_tenant),
    db=Depends(get_db),
):
    try:
        query = {"date": date_str, "tenant": tenant}
        if class_no:
            query["class_no"] = class_no
        if section:
            query["section"] = section
        if subject:
            query["subject"] = subject

        records = await db.student_interventions.find(query).to_list(length=300)

        # Resolve student names / roll numbers
        sids = list({r["student_id"] for r in records if "student_id" in r})
        students = await db.students.find({
            "tenant": tenant,
            "$or": [
                {"student_id": {"$in": sids}},
                {"_id": {"$in": [s for s in sids if len(str(s)) == 24]}},
            ]
        }).to_list(length=300)
        smap = {}
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
                id=str(r.get("_id")),
                rollNo=str(roll),
                student=name,
                topic=r.get("topic"),
                initial_score=float(r.get("initial_score", 0.0)),
                intervention_type=r.get("intervention_type"),
                gap_concept=r.get("gap_concept"),
                verification_score=r.get("verification_score"),
                learning_gain=gain,
                status=status,
            ))

        rows.sort(key=lambda x: x.rollNo)
        avg_gain = round(sum(gains) / len(gains), 1) if gains else 0.0

        return InterventionInsightsResponse(
            rows=rows,
            avg_learning_gain=avg_gain,
            improved_count=improved,
            needs_support_count=needs,
            mastered_count=mastered,
            total=len(rows),
        )
    except Exception as e:
        print(f"Error fetching intervention insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))
