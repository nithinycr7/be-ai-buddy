"""
Daily Quiz API Endpoints
Handles auto-generation, student submission, XP/streak tracking
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel

from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from ..models.schemas import (
    Quiz, QuizQuestion, StudentQuizAttempt, StreakTracking, QuizAnalytics,
    QuizPublic, AnswerVerificationRequest, AnswerVerificationResponse
)
from ..services.auto_quiz_generator import AutoQuizGenerator

router = APIRouter(prefix="/daily-quiz", tags=["daily-quiz"], dependencies=[Depends(api_key_guard)])


# ============================================
# Request/Response Models
# ============================================

class GenerateQuizRequest(BaseModel):
    daily_id: str
    force_regenerate: bool = False


class SubmitQuizRequest(BaseModel):
    quiz_id: str
    daily_id: str
    student_id: str
    responses: Dict[str, Any]  # {qid: {answer, time_spent, hint_used}}
    time_taken_seconds: int


class QuizSubmissionResponse(BaseModel):
    attempt_id: str
    score: float
    correct_count: int
    total_questions: int
    xp_earned: int
    current_streak: int
    badges_earned: list[str] = []


# ============================================
# Quiz Generation Endpoints
# ============================================

@router.post("/generate", response_model=Quiz)
async def generate_daily_quiz(
    request: GenerateQuizRequest,
    tenant: str = Depends(get_tenant)
):
    """
    Generate quiz for a daily class
    - Extracts metadata from transcript
    - Generates 6-question structured quiz
    - Falls back to revision quiz if confidence is low
    """
    db = await get_db()
    generator = AutoQuizGenerator(db)
    
    quiz_doc = await generator.generate_quiz_for_daily_class(
        daily_id=request.daily_id,
        tenant=tenant,
        force_regenerate=request.force_regenerate
    )
    
    if not quiz_doc:
        raise HTTPException(status_code=500, detail="Failed to generate quiz")
    
    # Convert _id to string for response
    if "_id" in quiz_doc:
        quiz_doc["id"] = str(quiz_doc["_id"])
        del quiz_doc["_id"]
    
    if "daily_id" in quiz_doc:
        quiz_doc["daily_id"] = str(quiz_doc["daily_id"])
    
    return Quiz(**quiz_doc)


@router.get("/{daily_id}", response_model=QuizPublic)
async def get_daily_quiz(
    daily_id: str,
    student_id: Optional[str] = None,
    tenant: str = Depends(get_tenant)
):
    """Get quiz for a daily class"""
    db = await get_db()
    
    from bson import ObjectId
    try:
        daily_oid = ObjectId(daily_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid daily_id format")

    quiz = await db.quizzes.find_one({
        "daily_id": daily_oid,
        "tenant": tenant
    })

    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found for this class")
    
    # Check for previous attempts
    if student_id:
        attempt = await db.student_quiz_attempts.find_one(
            {
                "daily_id": daily_id, 
                "student_id": student_id,
                "tenant": tenant
            },
            sort=[("attempt_number", -1)]
        )
        
        if attempt:
            if "_id" in attempt:
                attempt["id"] = str(attempt["_id"])
                del attempt["_id"]
            quiz["previous_attempt"] = attempt

    if "_id" in quiz:
        quiz["id"] = str(quiz["_id"])
        del quiz["_id"]
    
    if "daily_id" in quiz:
        quiz["daily_id"] = str(quiz["daily_id"])
    
    # Pydantic will filter fields based on QuizPublic
    return QuizPublic(**quiz)


@router.post("/verify-answer", response_model=AnswerVerificationResponse)
async def verify_answer(
    request: AnswerVerificationRequest,
    tenant: str = Depends(get_tenant)
):
    """
    Securely verify a single answer
    - attempt_number=1: If wrong, returns hint (if available)
    - attempt_number>=2: If wrong, returns correct answer + explanation
    - If correct: Returns explanation
    - Persists progress to DB
    """
    db = await get_db()
    from bson import ObjectId
    
    try:
        quiz_oid = ObjectId(request.quiz_id)
    except:
         raise HTTPException(status_code=400, detail="Invalid quiz_id format")

    quiz = await db.quizzes.find_one({"_id": quiz_oid})
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    # Find question
    question = next((q for q in quiz.get("questions", []) if q["qid"] == request.qid), None)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    correct_answer = question.get("correct", [])
    
    # Normalize
    user_ans = request.answer
    if isinstance(user_ans, str): user_ans = [user_ans]
    if isinstance(correct_answer, str): correct_answer = [correct_answer]
    
    user_set = set(str(x).lower().strip() for x in user_ans)
    correct_set = set(str(x).lower().strip() for x in correct_answer)
    
    is_correct = user_set == correct_set
    
    response = AnswerVerificationResponse(
        is_correct=is_correct,
        message="Correct!" if is_correct else "Incorrect"
    )
    
    if is_correct:
         response.explanation = question.get("explanation")
         response.xp_earned = 10 
    else:
        if request.attempt_number == 1:
             response.message = "Not quite right. Here is a hint."
             response.hint = question.get("hint")
        else:
             response.message = "Incorrect. The correct answer is shown below."
             response.explanation = question.get("explanation")
             response.correct_answer = question.get("correct")
             
    # Persist Progress
    # Find existing attempt or create new one
    attempt_query = {
        "daily_id": request.daily_id,
        "student_id": request.student_id,
        "tenant": tenant,
        "completed_at": None # Only update active attempts
    }
    
    # Check if any attempt exists (even completed, to prevent duplicate active ones if needed? 
    # For now assume one active attempt at a time logic)
    
    update_data = {
        f"responses.{request.qid}": {
            "answer": request.answer,
            "is_correct": is_correct,
            "attempt_number": request.attempt_number,
            "server_feedback": response.model_dump(),
            "timestamp": datetime.now().isoformat()
        },
        "updated_at": datetime.now().isoformat()
    }
    
    # If correct, we might want to check if all questions are answered to mark complete?
    # But client explicitly calls /submit for that usually. 
    # Let's just track progress here.
    
    await db.student_quiz_attempts.update_one(
        attempt_query,
        {"$set": update_data, "$setOnInsert": {"quiz_id": request.quiz_id, "started_at": datetime.now().isoformat()}},
        upsert=True
    )
    
    return response


# ============================================
# Student Submission & Scoring
# ============================================


@router.post("/submit", response_model=QuizSubmissionResponse)
async def submit_daily_quiz(
    request: SubmitQuizRequest,
    tenant: str = Depends(get_tenant)
):
    """
    Submit quiz responses and calculate score/XP
    - Scores different question types
    - Calculates XP with bonuses
    - Updates streak tracking
    - Stores analytics data
    """
    db = await get_db()
    
    # 1. Get quiz
    from bson import ObjectId
    quiz = await db.quizzes.find_one({"_id": ObjectId(request.quiz_id)})

    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    # 2. Calculate score
    questions = quiz.get("questions", [])
    total_questions = len(questions)
    correct_count = 0
    detailed_responses = {}
    
    for q in questions:
        qid = q["qid"]
        student_response = request.responses.get(qid, {})
        student_answer = student_response.get("answer", [])
        correct_answer = q.get("correct", [])
        
        # Normalize answers for comparison
        if isinstance(student_answer, str):
            student_answer = [student_answer.strip().lower()]
        if isinstance(correct_answer, str):
            correct_answer = [correct_answer.strip().lower()]
        
        # Check if correct
        is_correct = set(student_answer) == set(correct_answer)
        if is_correct:
            correct_count += 1
        
        # Store detailed response
        detailed_responses[qid] = {
            "answer": student_answer,
            "is_correct": is_correct,
            "time_spent": student_response.get("time_spent", 0),
            "hint_used": student_response.get("hint_used", False)
        }
    
    score = (correct_count / total_questions * 100) if total_questions > 0 else 0
    
    # 3. Calculate XP
    xp_earned = calculate_xp(
        correct_count=correct_count,
        total_questions=total_questions,
        responses=detailed_responses,
        time_taken=request.time_taken_seconds
    )
    
    # 4. Get attempt number
    existing_attempts = await db.student_quiz_attempts.count_documents({
        "quiz_id": request.quiz_id,
        "student_id": request.student_id
    })
    attempt_number = existing_attempts + 1
    
    # 5. Store attempt
    now = datetime.utcnow().isoformat() + "Z"
    attempt_doc = {
        "quiz_id": request.quiz_id,
        "student_id": request.student_id,
        "daily_id": request.daily_id,
        "tenant": tenant,
        "attempt_number": attempt_number,
        "started_at": now,
        "completed_at": now,
        "responses": detailed_responses,
        "score": score,
        "xp_earned": xp_earned,
        "time_taken_seconds": request.time_taken_seconds
    }
    
    result = await db.student_quiz_attempts.insert_one(attempt_doc)
    attempt_id = str(result.inserted_id)
    
    # 6. Update streak tracking
    streak_data = await update_streak_tracking(
        db=db,
        student_id=request.student_id,
        tenant=tenant,
        xp_earned=xp_earned,
        score=score
    )
    
    # 7. Update analytics
    await update_quiz_analytics(
        db=db,
        quiz_id=request.quiz_id,
        tenant=tenant,
        responses=detailed_responses
    )
    
    return QuizSubmissionResponse(
        attempt_id=attempt_id,
        score=score,
        correct_count=correct_count,
        total_questions=total_questions,
        xp_earned=xp_earned,
        current_streak=streak_data["current_streak"],
        badges_earned=streak_data.get("new_badges", [])
    )


# ============================================
# Streak & XP Endpoints
# ============================================

@router.get("/streak/{student_id}", response_model=StreakTracking)
async def get_student_streak(
    student_id: str,
    tenant: str = Depends(get_tenant)
):
    """Get student's streak and XP data"""
    db = await get_db()
    
    streak = await db.streak_tracking.find_one({
        "student_id": student_id,
        "tenant": tenant
    })
    
    if not streak:
        # Return default streak data
        return StreakTracking(
            student_id=student_id,
            tenant=tenant,
            current_streak=0,
            longest_streak=0,
            total_xp=0,
            badges=[],
            updated_at=datetime.utcnow().isoformat() + "Z"
        )
    
    if "_id" in streak:
        streak["id"] = str(streak["_id"])
        del streak["_id"]
    
    return StreakTracking(**streak)


# ============================================
# Helper Functions
# ============================================

def calculate_xp(
    correct_count: int,
    total_questions: int,
    responses: Dict[str, Any],
    time_taken: int
) -> int:
    """
    Calculate XP earned
    - Base: 10 XP per correct answer
    - Bonus: +5 for no hints used
    - Bonus: +3 for fast answers (<10s per question)
    """
    base_xp = correct_count * 10
    
    # No-hint bonus
    no_hint_bonus = 0
    for qid, resp in responses.items():
        if resp["is_correct"] and not resp.get("hint_used", False):
            no_hint_bonus += 5
    
    # Speed bonus (if avg time per question < 10s)
    speed_bonus = 0
    avg_time_per_question = time_taken / total_questions if total_questions > 0 else 999
    if avg_time_per_question < 10:
        speed_bonus = correct_count * 3
    
    total_xp = base_xp + no_hint_bonus + speed_bonus
    return total_xp


async def update_streak_tracking(
    db,
    student_id: str,
    tenant: str,
    xp_earned: int,
    score: float
) -> Dict[str, Any]:
    """
    Update student's streak and badges
    Returns updated streak data with new badges
    """
    now = datetime.utcnow().isoformat() + "Z"
    today = datetime.utcnow().date().isoformat()
    
    # Get existing streak
    streak = await db.streak_tracking.find_one({
        "student_id": student_id,
        "tenant": tenant
    })
    
    if not streak:
        streak = {
            "student_id": student_id,
            "tenant": tenant,
            "current_streak": 0,
            "longest_streak": 0,
            "total_xp": 0,
            "badges": [],
            "last_quiz_date": None,
            "updated_at": now
        }
    
    # Update streak (only if score > 50%)
    if score >= 50:
        last_date = streak.get("last_quiz_date")
        if last_date and last_date == today:
            # Already completed today, don't increment streak
            pass
        else:
            streak["current_streak"] += 1
            streak["last_quiz_date"] = today
    else:
        # Reset streak if score < 50%
        streak["current_streak"] = 0
    
    # Update longest streak
    if streak["current_streak"] > streak.get("longest_streak", 0):
        streak["longest_streak"] = streak["current_streak"]
    
    # Update total XP
    streak["total_xp"] = streak.get("total_xp", 0) + xp_earned
    
    # Check for new badges
    new_badges = []
    existing_badges = streak.get("badges", [])
    
    if streak["current_streak"] >= 3 and "3-Day Streak" not in existing_badges:
        new_badges.append("3-Day Streak")
        streak["badges"].append("3-Day Streak")
    
    if score == 100 and "Perfect Score" not in existing_badges:
        new_badges.append("Perfect Score")
        streak["badges"].append("Perfect Score")
    
    if streak["total_xp"] >= 1000 and "XP Master" not in existing_badges:
        new_badges.append("XP Master")
        streak["badges"].append("XP Master")
    
    streak["updated_at"] = now
    
    # Upsert
    await db.streak_tracking.update_one(
        {"student_id": student_id, "tenant": tenant},
        {"$set": streak},
        upsert=True
    )
    
    streak["new_badges"] = new_badges
    return streak


async def update_quiz_analytics(
    db,
    quiz_id: str,
    tenant: str,
    responses: Dict[str, Any]
):
    """
    Update analytics for each question
    """
    for qid, resp in responses.items():
        # Update or create analytics doc
        await db.quiz_analytics.update_one(
            {
                "quiz_id": quiz_id,
                "question_id": qid,
                "tenant": tenant
            },
            {
                "$inc": {
                    "total_attempts": 1,
                    "correct_count": 1 if resp["is_correct"] else 0,
                    "hint_usage_count": 1 if resp.get("hint_used", False) else 0
                },
                "$push": {
                    "time_samples": resp.get("time_spent", 0)
                }
            },
            upsert=True
        )
