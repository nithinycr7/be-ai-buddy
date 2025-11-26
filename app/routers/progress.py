from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, date
from typing import Optional, List
from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from ..models.schemas import StudentProgress
from pydantic import BaseModel

router = APIRouter(prefix="/progress", tags=["progress"], dependencies=[Depends(api_key_guard)])

class TrackActivityRequest(BaseModel):
    student_id: str
    daily_id: str
    activity: str  # "summary_viewed" or "story_generated"
    story_id: Optional[str] = None

def calculate_completion(progress_doc: dict) -> tuple[float, bool]:
    """Calculate completion percentage and status based on activities."""
    completion = 0.0
    
    # Summary: 25%
    if progress_doc.get("summary_viewed"):
        completion += 25.0
    
    # Story: 25%
    if progress_doc.get("story_generated"):
        completion += 25.0
    
    # Quiz: 50% (scaled by best score)
    if progress_doc.get("quiz_best_score") is not None:
        completion += (progress_doc["quiz_best_score"] / 100.0) * 50.0
    
    is_completed = completion >= 75.0
    return completion, is_completed

@router.post("/track")
async def track_activity(request: TrackActivityRequest, tenant: str = Depends(get_tenant)):
    """Track student activity (summary viewed or story generated)."""
    db = await get_db()
    
    # Get daily class info for validation
    from bson import ObjectId
    daily_class = await db.classes_daily.find_one({"_id": ObjectId(request.daily_id)})
    if not daily_class:
        raise HTTPException(status_code=404, detail="Daily class not found")
    
    # Find or create progress document
    progress = await db.student_progress.find_one({
        "student_id": request.student_id,
        "daily_id": request.daily_id
    })
    
    now = datetime.utcnow().isoformat() + "Z"
    
    if not progress:
        # Create new progress document
        progress = {
            "student_id": request.student_id,
            "daily_id": request.daily_id,
            "tenant": tenant,
            "date": daily_class["date"],
            "class_no": daily_class["class_no"],
            "section": daily_class["section"],
            "subject": daily_class["subject"],
            "summary_viewed": False,
            "story_generated": False,
            "quiz_taken": False,
            "quiz_attempts": 0,
            "completion_percentage": 0.0,
            "is_completed": False,
            "created_at": now,
            "updated_at": now
        }
    
    # Update based on activity
    update_fields = {"updated_at": now}
    
    if request.activity == "summary_viewed":
        update_fields["summary_viewed"] = True
        update_fields["summary_viewed_at"] = now
    elif request.activity == "story_generated":
        update_fields["story_generated"] = True
        update_fields["story_generated_at"] = now
        if request.story_id:
            update_fields["story_id"] = request.story_id
    else:
        raise HTTPException(status_code=400, detail="Invalid activity type")
    
    # Update progress document
    progress.update(update_fields)
    
    # Recalculate completion
    completion, is_completed = calculate_completion(progress)
    progress["completion_percentage"] = completion
    progress["is_completed"] = is_completed
    
    if is_completed and not progress.get("completed_at"):
        progress["completed_at"] = now
    
    # Upsert to database
    await db.student_progress.update_one(
        {"student_id": request.student_id, "daily_id": request.daily_id},
        {"$set": progress},
        upsert=True
    )
    
    # Return updated progress
    if "_id" in progress:
        progress["id"] = str(progress["_id"])
        del progress["_id"]
    
    return progress

@router.get("", response_model=List[StudentProgress])
async def get_progress(
    student_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tenant: str = Depends(get_tenant)
):
    """Get student progress for a date range."""
    db = await get_db()
    
    query = {"student_id": student_id, "tenant": tenant}
    
    if start_date:
        query.setdefault("date", {})["$gte"] = start_date
    if end_date:
        query.setdefault("date", {})["$lte"] = end_date
    
    cursor = db.student_progress.find(query).sort("date", -1)
    results = []
    
    async for doc in cursor:
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        results.append(StudentProgress(**doc))
    
    return results

@router.get("/weekly")
async def get_weekly_summary(
    student_id: str,
    start_date: str,  # YYYY-MM-DD
    tenant: str = Depends(get_tenant)
):
    """Get weekly progress summary."""
    db = await get_db()
    
    pipeline = [
        {
            "$match": {
                "student_id": student_id,
                "tenant": tenant,
                "date": {"$gte": start_date}
            }
        },
        {
            "$group": {
                "_id": "$date",
                "total_classes": {"$sum": 1},
                "completed_classes": {
                    "$sum": {"$cond": ["$is_completed", 1, 0]}
                },
                "avg_completion": {"$avg": "$completion_percentage"}
            }
        },
        {
            "$sort": {"_id": 1}
        }
    ]
    
    cursor = db.student_progress.aggregate(pipeline)
    results = []
    
    async for doc in cursor:
        results.append({
            "date": doc["_id"],
            "total_classes": doc["total_classes"],
            "completed_classes": doc["completed_classes"],
            "avg_completion": round(doc["avg_completion"], 2)
        })
    
    return results
