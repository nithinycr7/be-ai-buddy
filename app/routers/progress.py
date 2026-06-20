from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, date
from typing import Optional, List
from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from ..models.schemas import StudentDailyProgress

# ...

from pydantic import BaseModel

router = APIRouter(prefix="/progress", tags=["progress"], dependencies=[Depends(api_key_guard)])

class TrackActivityRequest(BaseModel):
    student_id: str
    daily_id: str
    activity: str  # "summary_viewed" or "story_generated"
    story_id: Optional[str] = None


def calculate_total_score(progress_doc: dict) -> float:
    """Calculate total score based on activities."""
    score = 0.0
    
    # Summary: 10%
    if progress_doc.get("summary_viewed"):
        score += 10.0
    
    # Story: 10%
    if progress_doc.get("story_generated"):
        score += 10.0
    
    # Quiz: Up to 80% (Already calculated and stored in quiz_score)
    score += progress_doc.get("quiz_score", 0.0)
    
    return min(score, 100.0)

@router.post("/track")
async def track_activity(request: TrackActivityRequest, tenant: str = Depends(get_tenant)):
    """Track student activity (summary viewed or story generated)."""
    db = await get_db()
    
    # Get daily class info for validation
    from bson import ObjectId
    try:
        daily_oid = ObjectId(request.daily_id)
        daily_class = await db.classes_daily.find_one({"_id": daily_oid, "tenant": tenant})
    except:
        raise HTTPException(status_code=400, detail="Invalid daily_id")

    if not daily_class:
        raise HTTPException(status_code=404, detail="Daily class not found")

    # Find or create progress document
    # Using 'student_daily_progress' collection as per new design
    progress = await db.student_daily_progress.find_one({
        "student_id": request.student_id,
        "daily_id": request.daily_id,
        "tenant": tenant
    })
    
    now = datetime.utcnow().isoformat()
    
    if not progress:
        # Create new progress document
        progress = {
            "student_id": request.student_id,
            "daily_id": request.daily_id,
            "tenant": tenant,
            "school_id": daily_class.get("school_id"), # Assuming school_id is in daily_class
            "date": daily_class.get("date"),
            "summary_viewed": False,
            "story_generated": False,
            "quiz_score": 0.0,
            "quiz_attempts": 0,
            "total_score": 0.0,
            "is_complete": False,
            "created_at": now,
            "updated_at": now
        }
    
    # Update based on activity
    update_fields = {"updated_at": now}
    
    if request.activity == "summary_viewed":
        update_fields["summary_viewed"] = True
        progress["summary_viewed"] = True
    elif request.activity == "story_generated":
        update_fields["story_generated"] = True
        progress["story_generated"] = True
    else:
        raise HTTPException(status_code=400, detail="Invalid activity type")
    
    # Recalculate score
    new_total = calculate_total_score(progress)
    progress["total_score"] = new_total
    update_fields["total_score"] = new_total
    
    # Upsert to database
    await db.student_daily_progress.update_one(
        {"student_id": request.student_id, "daily_id": request.daily_id, "tenant": tenant},
        {"$set": update_fields, "$setOnInsert": {
            k: v for k, v in progress.items() if k not in update_fields and k != "total_score"
        }},
        upsert=True
    )
    
    # Return updated progress
    if "_id" in progress:
        progress["id"] = str(progress["_id"])
        del progress["_id"]
    
    return progress

@router.get("", response_model=List[StudentDailyProgress])
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
    
    # Updated to use new collection
    cursor = db.student_daily_progress.find(query).sort("date", -1)
    results = []
    
    async for doc in cursor:
        if "_id" in doc:
            doc["id"] = str(doc["_id"]) # Ensure id mapping
            del doc["_id"]
        results.append(StudentDailyProgress(**doc))
    
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
                    "$sum": {"$cond": ["$is_complete", 1, 0]}
                },
                "avg_completion": {"$avg": "$total_score"}
            }
        },
        {
            "$sort": {"_id": 1}
        }
    ]
    
    # Updated to use new collection
    cursor = db.student_daily_progress.aggregate(pipeline)
    results = []
    
    async for doc in cursor:
        results.append({
            "date": doc["_id"],
            "total_classes": doc["total_classes"],
            "completed_classes": doc["completed_classes"],
            "avg_completion": round(doc["avg_completion"], 2)
        })
    
    return results
