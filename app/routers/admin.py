from fastapi import APIRouter, Depends
from ..core.security import api_key_guard
from ..db.mongo import get_db

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(api_key_guard)])

@router.get("/teacher-performance")
async def teacher_performance(teacher_email: str):
    db = await get_db()
    # Placeholder metrics: average quiz score per class taught
    pipeline = [
        {"$lookup": {"from": "quizzes", "localField": "daily_id", "foreignField": "_id", "as": "quiz"}},
    ]
    # For demo, return counts by class
    # In a real system we'd join teacher->class sessions; here we stub
    counts = await db.quizzes.count_documents({})
    avg_score = await db.quiz_responses.aggregate([{"$group":{"_id":None,"avg":{"$avg":"$score"}}}]).to_list(1)
    return {"teacher_email": teacher_email, "quizzes_created": counts, "avg_quiz_score": (avg_score[0]["avg"] if avg_score else None)}
