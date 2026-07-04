"""
Daily-quiz business logic: generation, secure answer verification, weighted
scoring, XP, streaks, analytics.

router → DailyQuizService → repositories (+ AutoQuizGenerator engine for generation).
The service never touches Motor directly and never raises HTTPException.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Depends

from ..core.exceptions import AppError, NotFoundError
from ..core.security import CurrentUser, assert_can_access_student
from ..db.mongo import get_db  # provider-only: to construct the AutoQuizGenerator engine
from ..db.repositories import (
    DailyClassRepository, get_daily_repo,
    QuizAnalyticsRepository, get_quiz_analytics_repo,
    QuizAttemptRepository, get_quiz_attempt_repo,
    QuizRepository, get_quiz_repo,
    StreakRepository, get_streak_repo,
    StudentDailyProgressRepository, get_daily_progress_repo,
)
from ..models.schemas import (
    AnswerVerificationRequest, AnswerVerificationResponse,
    Quiz, QuizPublic, StreakTracking,
)
from ..services.auto_quiz_generator import AutoQuizGenerator

DIFFICULTY_WEIGHTS = {"easy": 1.0, "medium": 2.0, "hard": 3.0}


def calculate_xp(*, correct_count: int, total_questions: int,
                 responses: Dict[str, Any], time_taken: int) -> int:
    """10 XP/correct + 5 no-hint bonus + speed bonus (<10s/question avg)."""
    base_xp = correct_count * 10
    no_hint_bonus = sum(5 for resp in responses.values()
                        if resp["is_correct"] and not resp.get("hint_used", False))
    avg_time_per_question = time_taken / total_questions if total_questions > 0 else 999
    speed_bonus = correct_count * 3 if avg_time_per_question < 10 else 0
    return base_xp + no_hint_bonus + speed_bonus


class DailyQuizService:
    def __init__(self, quizzes: QuizRepository, daily: DailyClassRepository,
                 attempts: QuizAttemptRepository, progress: StudentDailyProgressRepository,
                 streak: StreakRepository, analytics: QuizAnalyticsRepository,
                 generator: AutoQuizGenerator):
        self.quizzes = quizzes
        self.daily = daily
        self.attempts = attempts
        self.progress = progress
        self.streak = streak
        self.analytics = analytics
        self.generator = generator

    async def generate(self, *, daily_id: str, force_regenerate: bool) -> Quiz:
        quiz_doc = await self.generator.generate_quiz_for_daily_class(
            daily_id=daily_id, tenant=self.quizzes.tenant, force_regenerate=force_regenerate,
        )
        if not quiz_doc:
            raise AppError("Failed to generate quiz")  # -> 500
        if "_id" in quiz_doc:
            quiz_doc["id"] = str(quiz_doc["_id"])
            del quiz_doc["_id"]
        if "daily_id" in quiz_doc:
            quiz_doc["daily_id"] = str(quiz_doc["daily_id"])
        return Quiz(**quiz_doc)

    async def get_for_daily(self, *, daily_id: str, student_id: Optional[str],
                            requester: CurrentUser) -> QuizPublic:
        assert_can_access_student(requester, student_id)
        quiz = await self.quizzes.get_by_daily_oid(daily_id)  # InvalidObjectId -> 400
        if not quiz:
            raise NotFoundError("Quiz not found for this class")

        if student_id:
            attempt = await self.attempts.latest_for_daily(daily_id=daily_id, student_id=student_id)
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
        return QuizPublic(**quiz)

    async def verify_answer(self, request: AnswerVerificationRequest, *,
                            requester: CurrentUser) -> AnswerVerificationResponse:
        assert_can_access_student(requester, request.student_id)

        quiz = await self.quizzes.get(request.quiz_id)  # InvalidObjectId -> 400
        if not quiz:
            raise NotFoundError("Quiz not found")

        question = next((q for q in quiz.get("questions", []) if q["qid"] == request.qid), None)
        if not question:
            raise NotFoundError("Question not found")

        correct_answer = question.get("correct", [])
        user_ans = request.answer
        if isinstance(user_ans, str):
            user_ans = [user_ans]
        if isinstance(correct_answer, str):
            correct_answer = [correct_answer]
        user_set = {str(x).lower().strip() for x in user_ans}
        correct_set = {str(x).lower().strip() for x in correct_answer}
        is_correct = user_set == correct_set

        response = AnswerVerificationResponse(
            is_correct=is_correct, message="Correct!" if is_correct else "Incorrect")
        if is_correct:
            response.explanation = question.get("explanation")
            response.xp_earned = 10
        elif request.attempt_number == 1:
            response.message = "Not quite right. Here is a hint."
            response.hint = question.get("hint")
        else:
            response.message = "Incorrect. The correct answer is shown below."
            response.explanation = question.get("explanation")
            response.correct_answer = question.get("correct")

        update_data = {
            f"responses.{request.qid}": {
                "answer": request.answer,
                "is_correct": is_correct,
                "attempt_number": request.attempt_number,
                "server_feedback": response.model_dump(),
                "timestamp": datetime.now().isoformat(),
            },
            "updated_at": datetime.now().isoformat(),
        }
        await self.attempts.record_answer(
            daily_id=request.daily_id, student_id=request.student_id,
            set_fields=update_data,
            insert_fields={"quiz_id": request.quiz_id, "started_at": datetime.now().isoformat()},
        )
        return response

    async def submit(self, *, quiz_id: str, daily_id: str, student_id: str,
                     responses: Dict[str, Any], time_taken_seconds: int,
                     requester: CurrentUser) -> Dict[str, Any]:
        assert_can_access_student(requester, student_id)

        quiz = await self.quizzes.get(quiz_id)  # InvalidObjectId -> 400
        if not quiz:
            raise NotFoundError("Quiz not found")

        attempt = await self.attempts.get_active(quiz_id=quiz_id, student_id=student_id)
        responses_db = attempt.get("responses", {}) if attempt else {}

        questions = quiz.get("questions", [])
        total_max_points = 0.0
        student_earned_points = 0.0
        correct_count = 0
        total_questions = len(questions)

        for q in questions:
            weight = DIFFICULTY_WEIGHTS.get(q.get("difficulty", "medium").lower(), 2.0)
            total_max_points += weight
            qid = q["qid"]
            resp_data = responses_db.get(qid)
            if resp_data:
                is_correct = resp_data.get("is_correct", False)
                attempt_num = resp_data.get("attempt_number", 1)
            else:
                student_response = responses.get(qid, {})
                ans = student_response.get("answer", [])
                corr = q.get("correct", [])
                if isinstance(ans, str):
                    ans = [ans.strip().lower()]
                if isinstance(corr, str):
                    corr = [corr.strip().lower()]
                is_correct = set(ans) == set(corr)
                attempt_num = 1
            if is_correct:
                correct_count += 1
                multiplier = 1.0 if attempt_num == 1 else 0.5
                student_earned_points += (weight * multiplier)

        quiz_score_80 = (student_earned_points / total_max_points * 80.0) if total_max_points > 0 else 0.0

        now = datetime.utcnow().isoformat()
        progress = await self.progress.get(student_id=student_id, daily_id=daily_id)
        if not progress:
            try:
                daily_class = await self.daily.get(daily_id)
            except Exception:
                daily_class = None
            class_date = daily_class.get("date") if daily_class else datetime.utcnow().date().isoformat()
            progress = {
                "student_id": student_id, "daily_id": daily_id, "date": class_date,
                "summary_viewed": False, "story_generated": False,
                "quiz_score": 0.0, "total_score": 0.0, "created_at": now,
            }

        progress["quiz_score"] = round(quiz_score_80, 2)
        progress["quiz_attempts"] = progress.get("quiz_attempts", 0) + 1
        attempted_qids = set(responses.keys())
        all_qids = {q["qid"] for q in questions}
        progress["is_complete"] = all_qids.issubset(attempted_qids)

        total = 0.0
        if progress.get("summary_viewed"):
            total += 10.0
        if progress.get("story_generated"):
            total += 10.0
        total += progress["quiz_score"]
        progress["total_score"] = min(total, 100.0)
        progress["updated_at"] = now

        progress.pop("_id", None)
        await self.progress.upsert(student_id=student_id, daily_id=daily_id, doc=progress)

        xp_earned = calculate_xp(correct_count=correct_count, total_questions=total_questions,
                                 responses=responses, time_taken=time_taken_seconds)

        if attempt:
            await self.attempts.finalize(attempt["_id"], {
                "completed_at": now, "score": quiz_score_80,
                "raw_score_percent": (student_earned_points / total_max_points * 100) if total_max_points else 0,
                "xp_earned": xp_earned, "time_taken_seconds": time_taken_seconds,
            })
            attempt_id = str(attempt["_id"])
        else:
            res = await self.attempts.insert_one({
                "quiz_id": quiz_id, "student_id": student_id, "daily_id": daily_id,
                "attempt_number": 1, "started_at": now, "completed_at": now,
                "score": quiz_score_80, "xp_earned": xp_earned,
                "responses": responses, "time_taken_seconds": time_taken_seconds,
            })
            attempt_id = str(res.inserted_id)

        streak_data = await self._update_streak(
            student_id=student_id, xp_earned=xp_earned, score=progress["total_score"])
        await self._update_analytics(quiz_id=quiz_id, responses=responses)

        return {
            "attempt_id": attempt_id,
            "score": quiz_score_80,
            "correct_count": correct_count,
            "total_questions": total_questions,
            "xp_earned": xp_earned,
            "current_streak": streak_data["current_streak"],
            "badges_earned": streak_data.get("new_badges", []),
        }

    async def get_streak(self, *, student_id: str, requester: CurrentUser) -> StreakTracking:
        assert_can_access_student(requester, student_id)
        streak = await self.streak.get(student_id)
        if not streak:
            return StreakTracking(
                student_id=student_id, tenant=self.streak.tenant,
                current_streak=0, longest_streak=0, total_xp=0, badges=[],
                updated_at=datetime.utcnow().isoformat() + "Z")
        if "_id" in streak:
            streak["id"] = str(streak["_id"])
            del streak["_id"]
        return StreakTracking(**streak)

    # ── internal ─────────────────────────────────────────────────────────────
    async def _update_streak(self, *, student_id: str, xp_earned: int, score: float) -> Dict[str, Any]:
        now = datetime.utcnow().isoformat() + "Z"
        today = datetime.utcnow().date().isoformat()
        streak = await self.streak.get(student_id)
        if not streak:
            streak = {
                "student_id": student_id, "tenant": self.streak.tenant,
                "current_streak": 0, "longest_streak": 0, "total_xp": 0,
                "badges": [], "last_quiz_date": None, "updated_at": now,
            }

        if score >= 50:
            if streak.get("last_quiz_date") != today:
                streak["current_streak"] += 1
                streak["last_quiz_date"] = today
        else:
            streak["current_streak"] = 0

        if streak["current_streak"] > streak.get("longest_streak", 0):
            streak["longest_streak"] = streak["current_streak"]
        streak["total_xp"] = streak.get("total_xp", 0) + xp_earned

        new_badges = []
        existing_badges = streak.get("badges", [])
        if streak["current_streak"] >= 3 and "3-Day Streak" not in existing_badges:
            new_badges.append("3-Day Streak"); streak["badges"].append("3-Day Streak")
        if score == 100 and "Perfect Score" not in existing_badges:
            new_badges.append("Perfect Score"); streak["badges"].append("Perfect Score")
        if streak["total_xp"] >= 1000 and "XP Master" not in existing_badges:
            new_badges.append("XP Master"); streak["badges"].append("XP Master")

        streak["updated_at"] = now
        streak.pop("_id", None)
        await self.streak.upsert(student_id, streak)
        streak["new_badges"] = new_badges
        return streak

    async def _update_analytics(self, *, quiz_id: str, responses: Dict[str, Any]) -> None:
        for qid, resp in responses.items():
            await self.analytics.bump(
                quiz_id=quiz_id, question_id=qid, is_correct=resp["is_correct"],
                hint_used=resp.get("hint_used", False), time_spent=resp.get("time_spent", 0))


def get_daily_quiz_service(
    quizzes: QuizRepository = Depends(get_quiz_repo),
    daily: DailyClassRepository = Depends(get_daily_repo),
    attempts: QuizAttemptRepository = Depends(get_quiz_attempt_repo),
    progress: StudentDailyProgressRepository = Depends(get_daily_progress_repo),
    streak: StreakRepository = Depends(get_streak_repo),
    analytics: QuizAnalyticsRepository = Depends(get_quiz_analytics_repo),
    db=Depends(get_db),
) -> DailyQuizService:
    # db is used only to build the AutoQuizGenerator engine (DI wiring, not a query).
    return DailyQuizService(quizzes, daily, attempts, progress, streak, analytics,
                            AutoQuizGenerator(db))
