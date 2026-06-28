from __future__ import annotations
from fastapi import APIRouter, Depends
from ..core.security import api_key_guard, get_tenant, require_role
from ..db.mongo import get_db

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("admin"))])

@router.get("/teacher-performance")
async def teacher_performance(teacher_email: str, tenant: str = Depends(get_tenant)):
    db = await get_db()
    # Counts/averages scoped to the requesting school only.
    counts = await db.quizzes.count_documents({"tenant": tenant})
    avg_score = await db.quiz_responses.aggregate([
        {"$match": {"tenant": tenant}},
        {"$group": {"_id": None, "avg": {"$avg": "$score"}}},
    ]).to_list(1)
    return {"teacher_email": teacher_email, "quizzes_created": counts, "avg_quiz_score": (avg_score[0]["avg"] if avg_score else None)}
