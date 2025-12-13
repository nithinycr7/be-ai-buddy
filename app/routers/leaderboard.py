from fastapi import APIRouter, Depends, HTTPException, Query
from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"], dependencies=[Depends(api_key_guard)])

class LeaderboardEntry(BaseModel):
    rank: int
    student_id: str
    name: str = "Unknown"
    avatar: Optional[str] = None
    xp: float

class LeaderboardResponse(BaseModel):
    top_5: List[LeaderboardEntry]
    user_rank: Optional[LeaderboardEntry] = None

@router.get("", response_model=LeaderboardResponse)
async def get_leaderboard(
    current_student_id: str,
    period: str = Query("weekly", enum=["weekly", "all_time"]),
    school_id: Optional[str] = None,
    tenant: str = Depends(get_tenant)
):
    """
    Get Leaderboard: Top 5 + Current User Rank
    - Period: weekly (current week) or all_time
    - Filters: tenant (Board), school_id (School)
    """
    db = await get_db()
    
    # 1. Build Base Match Stage
    match_stage = {"tenant": tenant}
    if school_id:
        match_stage["school_id"] = school_id
        
    if period == "weekly":
        # Start of current week (Monday)
        today = datetime.utcnow().date()
        start_of_week = today - timedelta(days=today.weekday())
        match_stage["date"] = {"$gte": start_of_week.isoformat()}
    
    # 2. Aggregation Helper
    async def aggregate_scores(match_filter):
        pipeline = [
            {"$match": match_filter},
            {"$group": {
                "_id": "$student_id",
                "total_xp": {"$sum": "$total_score"}
            }}
        ]
        return pipeline

    # 3. Get Top 5
    pipeline = await aggregate_scores(match_stage)
    pipeline.extend([
        {"$sort": {"total_xp": -1}},
        {"$limit": 5},
        # Join with students for name
        {"$lookup": {
            "from": "students",
            "localField": "_id",
            "foreignField": "student_id",
            "as": "student_info"
        }},
        {"$unwind": {"path": "$student_info", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "student_id": "$_id",
            "xp": "$total_xp",
            "first_name": "$student_info.first_name",
            "last_name": "$student_info.last_name",
            "avatar": "$student_info.avatar",
            "_id": 0
        }}
    ])
    
    cursor = db.student_daily_progress.aggregate(pipeline)
    top_5 = []
    
    rank_counter = 1
    async for doc in cursor:
        name = f"{doc.get('first_name', '')} {doc.get('last_name', '')}".strip() or "Student"
        entry = LeaderboardEntry(
            rank=rank_counter,
            student_id=doc["student_id"],
            name=name,
            avatar=doc.get("avatar"),
            xp=doc["xp"]
        )
        top_5.append(entry)
        rank_counter += 1
        
    # 4. Get User Rank
    user_entry = None
    if current_student_id:
        # A. Calculate User's XP
        user_xp_cursor = db.student_daily_progress.aggregate([
            {"$match": {**match_stage, "student_id": current_student_id}},
            {"$group": {"_id": "$student_id", "total_xp": {"$sum": "$total_score"}}}
        ])
        user_data = await user_xp_cursor.to_list(length=1)
        
        if user_data:
            user_xp = user_data[0]["total_xp"]
            
            # B. Count students with more XP
            # Need to re-aggregate all scores to count.
            # Optimized: Just match/group/match > user_xp / count ?? 
            # No, because "total_score" is spread across documents. We MUST group by student_id first.
            
            rank_pipeline = [
                {"$match": match_stage},
                {"$group": {
                    "_id": "$student_id",
                    "total_xp": {"$sum": "$total_score"}
                }},
                {"$match": {"total_xp": {"$gt": user_xp}}},
                {"$count": "higher_rank_count"}
            ]
            
            rank_res = await db.student_daily_progress.aggregate(rank_pipeline).to_list(length=1)
            rank = (rank_res[0]["higher_rank_count"] if rank_res else 0) + 1
            
            # Fetch user details (name)
            student_doc = await db.students.find_one({"student_id": current_student_id})
            name = "Me"
            avatar = None
            if student_doc:
                name = f"{student_doc.get('first_name', '')} {student_doc.get('last_name', '')}".strip()
                avatar = student_doc.get("avatar")
            
            user_entry = LeaderboardEntry(
                rank=rank,
                student_id=current_student_id,
                name=name,
                avatar=avatar,
                xp=user_xp
            )
        else:
            # User has no progress yet
            user_entry = LeaderboardEntry(
                rank=0, # unranked
                student_id=current_student_id,
                name="Me",
                xp=0
            )

    return LeaderboardResponse(top_5=top_5, user_rank=user_entry)
