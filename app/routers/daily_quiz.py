"""
Daily Quiz API Endpoints
Handles auto-generation, student submission, XP/streak tracking
"""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel

from ..core.security import get_tenant, require_role, get_current_user, CurrentUser, assert_can_access_student
from ..db.mongo import get_db  # only for constructing AutoQuizGenerator (a cross-collection service)
from ..db.repositories import (
    DailyClassRepository, get_daily_repo,
    QuizRepository, get_quiz_repo,
    QuizAttemptRepository, get_quiz_attempt_repo,
    StudentDailyProgressRepository, get_daily_progress_repo,
    StreakRepository, get_streak_repo,
    QuizAnalyticsRepository, get_quiz_analytics_repo,
)
from ..db.repositories.base import InvalidObjectId
from ..models.schemas import (
    Quiz, StreakTracking, QuizPublic,
    AnswerVerificationRequest, AnswerVerificationResponse
)
from ..services.auto_quiz_generator import AutoQuizGenerator

router = APIRouter(prefix="/daily-quiz", tags=["daily-quiz"], dependencies=[Depends(require_role("student", "parent", "teacher", "admin"))])


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
    tenant: str = Depends(get_tenant),
    user: CurrentUser = Depends(require_role("teacher", "admin")),
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
    quizzes: QuizRepository = Depends(get_quiz_repo),
    attempts: QuizAttemptRepository = Depends(get_quiz_attempt_repo),
    user: CurrentUser = Depends(get_current_user),
):
    """Get quiz for a daily class"""
    assert_can_access_student(user, student_id)

    try:
        quiz = await quizzes.get_by_daily_oid(daily_id)
    except InvalidObjectId:
        raise HTTPException(status_code=400, detail="Invalid daily_id format")

    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found for this class")

    # Check for previous attempts
    if student_id:
        attempt = await attempts.latest_for_daily(daily_id=daily_id, student_id=student_id)
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
    quizzes: QuizRepository = Depends(get_quiz_repo),
    attempts: QuizAttemptRepository = Depends(get_quiz_attempt_repo),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Securely verify a single answer
    - attempt_number=1: If wrong, returns hint (if available)
    - attempt_number>=2: If wrong, returns correct answer + explanation
    - If correct: Returns explanation
    - Persists progress to DB
    """
    assert_can_access_student(user, request.student_id)

    try:
        quiz = await quizzes.get(request.quiz_id)
    except InvalidObjectId:
        raise HTTPException(status_code=400, detail="Invalid quiz_id format")
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

    # Persist progress onto the active attempt (one graded answer)
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
    await attempts.record_answer(
        daily_id=request.daily_id,
        student_id=request.student_id,
        set_fields=update_data,
        insert_fields={"quiz_id": request.quiz_id, "started_at": datetime.now().isoformat()},
    )

    return response


# ============================================
# Student Submission & Scoring
# ============================================


@router.post("/submit", response_model=QuizSubmissionResponse)
async def submit_daily_quiz(
    request: SubmitQuizRequest,
    quizzes: QuizRepository = Depends(get_quiz_repo),
    daily: DailyClassRepository = Depends(get_daily_repo),
    attempts: QuizAttemptRepository = Depends(get_quiz_attempt_repo),
    progress_repo: StudentDailyProgressRepository = Depends(get_daily_progress_repo),
    streak_repo: StreakRepository = Depends(get_streak_repo),
    analytics_repo: QuizAnalyticsRepository = Depends(get_quiz_analytics_repo),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Submit quiz responses and calculate score/XP
    - Uses weighted scoring (Easy=1, Med=2, Hard=3)
    - Attempt penalty (1st=100%, 2nd=50%)
    - Updates StudentDailyProgress
    """
    assert_can_access_student(user, request.student_id)

    # 1. Get quiz
    try:
        quiz = await quizzes.get(request.quiz_id)
    except InvalidObjectId:
        raise HTTPException(status_code=400, detail="Invalid quiz_id format")
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    # 2. Get active attempt (populated by verify-answer)
    attempt = await attempts.get_active(quiz_id=request.quiz_id, student_id=request.student_id)

    # Fallback: if attempt doesn't exist, assume 1st attempt for everything (optimistic)
    responses_db = attempt.get("responses", {}) if attempt else {}

    # 3. Calculate Weighted Score
    questions = quiz.get("questions", [])
    total_max_points = 0.0
    student_earned_points = 0.0

    difficulty_weights = {"easy": 1.0, "medium": 2.0, "hard": 3.0}

    correct_count = 0
    total_questions = len(questions)

    for q in questions:
        diff = q.get("difficulty", "medium").lower()
        weight = difficulty_weights.get(diff, 2.0)
        total_max_points += weight

        qid = q["qid"]

        # Check DB response first (secure), then request payload
        resp_data = responses_db.get(qid)

        if resp_data:
            is_correct = resp_data.get("is_correct", False)
            attempt_num = resp_data.get("attempt_number", 1)
        else:
            # Fallback to trusted request; re-verify logical correctness
            student_response = request.responses.get(qid, {})
            ans = student_response.get("answer", [])
            corr = q.get("correct", [])

            if isinstance(ans, str): ans = [ans.strip().lower()]
            if isinstance(corr, str): corr = [corr.strip().lower()]

            is_correct = set(ans) == set(corr)
            attempt_num = 1  # Assume 1st attempt if not in DB

        if is_correct:
            correct_count += 1
            multiplier = 1.0 if attempt_num == 1 else 0.5  # Attempt penalty
            student_earned_points += (weight * multiplier)

    # Scale to 80% (Max Quiz Weight)
    quiz_score_80 = (student_earned_points / total_max_points * 80.0) if total_max_points > 0 else 0.0

    # 4. Update StudentDailyProgress
    now = datetime.utcnow().isoformat()
    progress = await progress_repo.get(student_id=request.student_id, daily_id=request.daily_id)

    if not progress:
        # Fetch daily class to get the date
        try:
            daily_class = await daily.get(request.daily_id)
        except InvalidObjectId:
            daily_class = None
        class_date = daily_class.get("date") if daily_class else datetime.utcnow().date().isoformat()

        progress = {
            "student_id": request.student_id,
            "daily_id": request.daily_id,
            "date": class_date,  # Critical for Insights filtering
            "summary_viewed": False,
            "story_generated": False,
            "quiz_score": 0.0,
            "total_score": 0.0,
            "created_at": now
        }

    progress["quiz_score"] = round(quiz_score_80, 2)
    progress["quiz_attempts"] = progress.get("quiz_attempts", 0) + 1

    # is_complete: attempted ALL quiz questions (regardless of correctness)
    attempted_qids = set(request.responses.keys())
    all_qids = set(q["qid"] for q in questions)
    progress["is_complete"] = all_qids.issubset(attempted_qids)

    # Recalculate Total Score (10 + 10 + 80)
    total = 0.0
    if progress.get("summary_viewed"): total += 10.0
    if progress.get("story_generated"): total += 10.0
    total += progress["quiz_score"]
    progress["total_score"] = min(total, 100.0)
    progress["updated_at"] = now

    progress.pop("_id", None)  # never $set the immutable _id
    await progress_repo.upsert(
        student_id=request.student_id, daily_id=request.daily_id, doc=progress
    )

    # 5. Finalize Attempt
    xp_earned = calculate_xp(
        correct_count=correct_count,
        total_questions=total_questions,
        responses=request.responses,  # detailed request responses for metrics like time_spent
        time_taken=request.time_taken_seconds
    )

    if attempt:
        await attempts.finalize(attempt["_id"], {
            "completed_at": now,
            "score": quiz_score_80,
            "raw_score_percent": (student_earned_points / total_max_points * 100) if total_max_points else 0,
            "xp_earned": xp_earned,
            "time_taken_seconds": request.time_taken_seconds
        })
        attempt_id = str(attempt["_id"])
    else:
        new_attempt = {
            "quiz_id": request.quiz_id,
            "student_id": request.student_id,
            "daily_id": request.daily_id,
            "attempt_number": 1,
            "started_at": now,
            "completed_at": now,
            "score": quiz_score_80,
            "xp_earned": xp_earned,
            "responses": request.responses,  # Fallback
            "time_taken_seconds": request.time_taken_seconds
        }
        res = await attempts.insert_one(new_attempt)
        attempt_id = str(res.inserted_id)

    # 6. Streak & Analytics
    streak_data = await update_streak_tracking(
        streak_repo=streak_repo,
        student_id=request.student_id,
        xp_earned=xp_earned,
        score=progress["total_score"]  # Use Total Score for streak threshold
    )

    await update_quiz_analytics(
        analytics_repo=analytics_repo,
        quiz_id=request.quiz_id,
        responses=request.responses
    )

    return QuizSubmissionResponse(
        attempt_id=attempt_id,
        score=quiz_score_80,
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
    streak_repo: StreakRepository = Depends(get_streak_repo),
    user: CurrentUser = Depends(get_current_user),
):
    """Get student's streak and XP data"""
    assert_can_access_student(user, student_id)

    streak = await streak_repo.get(student_id)

    if not streak:
        return StreakTracking(
            student_id=student_id,
            tenant=streak_repo.tenant,
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
    streak_repo: StreakRepository,
    student_id: str,
    xp_earned: int,
    score: float
) -> Dict[str, Any]:
    """
    Update student's streak and badges
    Returns updated streak data with new badges
    """
    now = datetime.utcnow().isoformat() + "Z"
    today = datetime.utcnow().date().isoformat()

    streak = await streak_repo.get(student_id)

    if not streak:
        streak = {
            "student_id": student_id,
            "tenant": streak_repo.tenant,
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
            pass  # Already completed today, don't increment streak
        else:
            streak["current_streak"] += 1
            streak["last_quiz_date"] = today
    else:
        streak["current_streak"] = 0  # Reset streak if score < 50%

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

    streak.pop("_id", None)  # never $set the immutable _id
    await streak_repo.upsert(student_id, streak)

    streak["new_badges"] = new_badges
    return streak


async def update_quiz_analytics(
    analytics_repo: QuizAnalyticsRepository,
    quiz_id: str,
    responses: Dict[str, Any]
):
    """Update analytics for each answered question."""
    for qid, resp in responses.items():
        await analytics_repo.bump(
            quiz_id=quiz_id,
            question_id=qid,
            is_correct=resp["is_correct"],
            hint_used=resp.get("hint_used", False),
            time_spent=resp.get("time_spent", 0),
        )
