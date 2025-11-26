from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from typing import Dict, List
from bson import ObjectId
from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from ..models.schemas import Quiz, QuizResponse
from pydantic import BaseModel

router = APIRouter(prefix="/quiz", tags=["quiz"], dependencies=[Depends(api_key_guard)])

class SubmitQuizRequest(BaseModel):
    student_id: str
    daily_id: str
    responses: Dict[str, List[str]]  # {qid: [selected_option]}
    time_taken_seconds: int = 0

@router.get("/{daily_id}", response_model=Quiz)
async def get_quiz(daily_id: str, tenant: str = Depends(get_tenant)):
    """Get quiz for a daily class."""
    db = await get_db()
    
    # Find quiz for this daily class
    quiz = await db.quizzes.find_one({"daily_id": daily_id, "tenant": tenant})
    
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found for this class")
    
    if "_id" in quiz:
        quiz["_id"] = str(quiz["_id"])
    
    return Quiz(**quiz)

@router.post("/submit")
async def submit_quiz(request: SubmitQuizRequest, tenant: str = Depends(get_tenant)):
    """Submit quiz responses and calculate score."""
    db = await get_db()
    
    # Get the quiz
    quiz = await db.quizzes.find_one({"daily_id": request.daily_id, "tenant": tenant})
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    # Get daily class info
    daily_class = await db.classes_daily.find_one({"_id": ObjectId(request.daily_id)})
    if not daily_class:
        raise HTTPException(status_code=404, detail="Daily class not found")
    
    # Build correct answers map
    correct_answers = {}
    for q in quiz["questions"]:
        correct_answers[q["qid"]] = q["correct"]
    
    # Calculate score
    correct_count = 0
    total_questions = len(quiz["questions"])
    
    for qid, student_answer in request.responses.items():
        if qid in correct_answers and student_answer == correct_answers[qid]:
            correct_count += 1
    
    score = (correct_count / total_questions) * 100 if total_questions > 0 else 0
    
    # Get existing responses to determine attempt number
    existing_responses = await db.quiz_responses.find({
        "daily_id": request.daily_id,
        "student_id": request.student_id
    }).sort("attempt_number", -1).limit(1).to_list(1)
    
    attempt_number = 1
    if existing_responses:
        attempt_number = existing_responses[0]["attempt_number"] + 1
    
    # Create quiz response document
    now = datetime.utcnow().isoformat() + "Z"
    quiz_response = {
        "daily_id": request.daily_id,
        "student_id": request.student_id,
        "quiz_id": str(quiz["_id"]),
        "tenant": tenant,
        "attempt_number": attempt_number,
        "attempted_at": now,
        "responses": request.responses,
        "correct_answers": correct_answers,
        "score": score,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "time_taken_seconds": request.time_taken_seconds
    }
    
    # Insert quiz response
    result = await db.quiz_responses.insert_one(quiz_response)
    quiz_response["_id"] = str(result.inserted_id)
    
    # Update student progress
    progress = await db.student_progress.find_one({
        "student_id": request.student_id,
        "daily_id": request.daily_id
    })
    
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
    
    # Update quiz fields
    progress["quiz_taken"] = True
    progress["quiz_id"] = str(quiz["_id"])
    progress["quiz_attempts"] = attempt_number
    progress["quiz_latest_score"] = score
    progress["quiz_last_attempt_at"] = now
    
    if attempt_number == 1:
        progress["quiz_first_attempt_at"] = now
        progress["quiz_best_score"] = score
    else:
        # Update best score if this attempt is better
        if score > progress.get("quiz_best_score", 0):
            progress["quiz_best_score"] = score
    
    progress["updated_at"] = now
    
    # Recalculate completion
    from .progress import calculate_completion
    completion, is_completed = calculate_completion(progress)
    progress["completion_percentage"] = completion
    progress["is_completed"] = is_completed
    
    if is_completed and not progress.get("completed_at"):
        progress["completed_at"] = now
    
    # Upsert progress
    await db.student_progress.update_one(
        {"student_id": request.student_id, "daily_id": request.daily_id},
        {"$set": progress},
        upsert=True
    )
    
    return {
        "quiz_response_id": quiz_response["_id"],
        "score": score,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "attempt_number": attempt_number,
        "best_score": progress["quiz_best_score"],
        "completion_percentage": completion,
        "is_completed": is_completed
    }

@router.get("/responses/{daily_id}")
async def get_quiz_responses(
    daily_id: str,
    student_id: str,
    tenant: str = Depends(get_tenant)
):
    """Get all quiz attempts for a student on a daily class."""
    db = await get_db()
    
    cursor = db.quiz_responses.find({
        "daily_id": daily_id,
        "student_id": student_id,
        "tenant": tenant
    }).sort("attempt_number", 1)
    
    results = []
    async for doc in cursor:
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        results.append(QuizResponse(**doc))
    
    return results