from fastapi import APIRouter, Depends, HTTPException, Query
from app.db.mongo import get_db
from app.core.security import get_tenant
from typing import List, Optional
from datetime import date
from pydantic import BaseModel

router = APIRouter()

class StudentInsight(BaseModel):
    id: str
    rollNo: str
    name: str
    score: float
    readSummary: bool
    readStory: bool
    status: str # Excellent, Good, Average, Needs Attention 

class InsightsResponse(BaseModel):
    distribution: List[dict] # {range: '0-40', count: 5}
    students: List[StudentInsight]
    class_average: float
    top_score: float

@router.get("", response_model=InsightsResponse)
async def get_class_insights(
    class_no: Optional[int] = Query(None, description="Class Number"),
    section: Optional[str] = Query(None, description="Section"),
    subject: Optional[str] = Query(None, description="Subject"),
    date_str: str = Query(..., alias="date", description="Date YYYY-MM-DD"),
    tenant: str = Depends(get_tenant),
    db=Depends(get_db)
):
    try:
        from datetime import datetime, timedelta
        
        start_date_str = date_str
        try:
            start_dt = datetime.strptime(date_str, "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=1)
            end_date_str = end_dt.strftime("%Y-%m-%d")
        except ValueError:
            # Fallback
            start_dt = datetime.now()
            end_dt = start_dt
            end_date_str = date_str

        # Query conditions — always scope to the requesting school.
        base_query = {"tenant": tenant}
        if class_no:
            base_query["class_no"] = class_no
        if section:
            base_query["section"] = section
        if subject:
            base_query["subject"] = subject

        # Date Query: Filter by the ASSIGNED CLASS DATE ("date" field)
        # This ensures that even if a student completes the work later (e.g. next day),
        # it is attributed to the correct Daily Class.
        
        date_query = {"date": date_str}
        
        # Merge queries
        query = {"$and": [base_query, date_query]} if base_query else date_query
        
        # 2. Fetch Progress Records
        progress_cursor = db.student_daily_progress.find(query)
        progress_data = await progress_cursor.to_list(length=100)
        
        if not progress_data:
             return InsightsResponse(
                distribution=[
                    {"range": "0-40", "count": 0},
                    {"range": "40-60", "count": 0},
                    {"range": "60-80", "count": 0},
                    {"range": "80-100", "count": 0}
                ],
                students=[],
                class_average=0.0,
                top_score=0.0
            )

        # 3. Collect Student IDs to fetch names
        # Handle both external IDs and ObjectIds if mixed, though normally consistent
        # We assume student_id in progress matches some field in students collection
        student_ids_to_fetch = list(set([p["student_id"] for p in progress_data if "student_id" in p]))

        # 4. Fetch Student Details (Name, etc.)
        # We try to match both 'student_id' (external) and '_id' (internal)
        # It's safer to query with $or if we are unsure, but user indicated external ID usage
        students_cursor = db.students.find({
            "$or": [
                {"student_id": {"$in": student_ids_to_fetch}},
                {"_id": {"$in": [oid for oid in student_ids_to_fetch if len(str(oid)) == 24]}} # Only valid OIDs
            ]
        })
        students = await students_cursor.to_list(length=100)
        
        # create map of student details
        # We can map by BOTH external ID and internal ID to be safe
        student_details_map = {}
        for s in students:
            if "student_id" in s:
                student_details_map[s["student_id"]] = s
            student_details_map[str(s["_id"])] = s

        # 5. Merge Data — collapse to one row per student.
        # When no subject filter is supplied, a student can have multiple
        # progress rows (one per subject) for the same day. We keep the row
        # with the highest quiz_latest_score so the table never shows duplicates.
        by_student: dict = {}
        for progress in progress_data:
            sid = progress.get("student_id")
            score = progress.get("quiz_latest_score", 0) or 0
            existing = by_student.get(sid)
            if existing is None or score > (existing.get("quiz_latest_score") or 0):
                by_student[sid] = progress
            else:
                # still merge read flags (any True wins) so the student isn't
                # marked unread just because the higher-scoring subject was unread
                existing["summary_viewed"] = existing.get("summary_viewed") or progress.get("summary_viewed", False)
                existing["story_generated"] = existing.get("story_generated") or progress.get("story_generated", False)

        insight_students = []
        scores = []

        for sid, progress in by_student.items():
            student = student_details_map.get(sid) or student_details_map.get(str(sid))

            student_name = student.get("name", "Unknown") if student else f"Student {sid}"
            roll_no = (
                student.get("roll_no") or student.get("student_id") or str(sid)
                if student else str(sid)
            )

            read_summary = progress.get("summary_viewed", False)
            read_story = progress.get("story_generated", False)

            quiz_score = 0
            if progress.get("quiz_taken"):
                raw_score = progress.get("quiz_latest_score", 0)
                quiz_score = raw_score or 0

            scores.append(quiz_score)

            status = "Needs Attention"
            if quiz_score >= 80:
                status = "Excellent"
            elif quiz_score >= 60:
                status = "Good"
            elif quiz_score >= 40:
                status = "Average"

            insight_students.append(StudentInsight(
                id=str(sid),
                rollNo=roll_no,
                name=student_name,
                score=quiz_score,
                readSummary=read_summary,
                readStory=read_story,
                status=status
            ))

        # 6. Calculate Distribution
        dist_counts = {
            "0-40": 0,
            "40-60": 0,
            "60-80": 0,
            "80-100": 0
        }
        
        for s in scores:
            if s < 40:
                dist_counts["0-40"] += 1
            elif s < 60:
                dist_counts["40-60"] += 1
            elif s < 80:
                dist_counts["60-80"] += 1
            else:
                dist_counts["80-100"] += 1
                
        distribution = [
            {"range": "0-40", "count": dist_counts["0-40"]},
            {"range": "40-60", "count": dist_counts["40-60"]},
            {"range": "60-80", "count": dist_counts["60-80"]},
            {"range": "80-100", "count": dist_counts["80-100"]}
        ]

        class_avg = sum(scores) / len(scores) if scores else 0
        top_score = max(scores) if scores else 0

        # Sort by rollNo
        insight_students.sort(key=lambda x: x.rollNo)

        return InsightsResponse(
            distribution=distribution,
            students=insight_students,
            class_average=round(class_avg, 1),
            top_score=round(top_score, 1)
        )

    except Exception as e:
        print(f"Error fetching insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))
