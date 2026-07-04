"""
Adaptive-intervention business logic.
router → InterventionService → (Quiz + Daily + QuizAttempt + Intervention repos).

The 3-tier analysis + verification scoring live here; the router just parses and
returns. Raises domain exceptions (never HTTPException).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from fastapi import Depends

from ..core.exceptions import NotFoundError
from ..core.security import CurrentUser, assert_can_access_student
from ..db.repositories import (
    DailyClassRepository, get_daily_repo,
    InterventionRepository, get_intervention_repo,
    QuizAttemptRepository, get_quiz_attempt_repo,
    QuizRepository, get_quiz_repo,
)
from ..db.repositories.base import InvalidObjectId
from ..models.schemas import (
    AnalyzeInterventionRequest, InterventionAnalyzeResponse,
    VerifyInterventionRequest, VerifyInterventionResponse,
)
from .intervention_engine import generate_intervention

# 3-tier thresholds (mastery %, 0-100)
MASTERED_THRESHOLD = 80.0
PREREQUISITE_THRESHOLD = 40.0
SUPPORT_THRESHOLD = 50.0  # below this after intervention -> needs teacher support


def _normalize_answer(value: Any) -> set:
    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    return {str(v).strip().lower() for v in value}


def _is_correct(student_answer: Any, correct: Any) -> bool:
    return _normalize_answer(student_answer) == _normalize_answer(correct)


def _tier_for(score: float) -> str:
    if score >= MASTERED_THRESHOLD:
        return "mastered"
    if score >= PREREQUISITE_THRESHOLD:
        return "prerequisite_gap"
    return "core_gap"


class InterventionService:
    def __init__(self, quizzes: QuizRepository, daily: DailyClassRepository,
                 attempts: QuizAttemptRepository, interventions: InterventionRepository):
        self.quizzes = quizzes
        self.daily = daily
        self.attempts = attempts
        self.interventions = interventions

    async def analyze(self, request: AnalyzeInterventionRequest, *,
                      requester: CurrentUser) -> InterventionAnalyzeResponse:
        assert_can_access_student(requester, request.student_id)

        quiz = await self.quizzes.get(request.quiz_id)  # InvalidObjectId -> 400 via handler
        if not quiz:
            raise NotFoundError("Quiz not found")

        # Idempotent: reuse a prior analysis for (student, daily, quiz).
        existing = await self.interventions.find_existing(
            student_id=request.student_id, daily_id=request.daily_id, quiz_id=request.quiz_id,
        )
        if existing:
            if existing.get("tier") == "mastered":
                return InterventionAnalyzeResponse(
                    intervention_id=None, tier="mastered", topic=existing.get("topic"),
                    initial_score=existing.get("initial_score", 0.0), verification_questions=[],
                )
            if existing.get("verification_questions"):
                public_qs = [
                    {"qid": q["qid"], "question": q["question"],
                     "question_type": q.get("question_type", "MCQ"),
                     "difficulty": q.get("difficulty", "easy"),
                     "options": q.get("options", [])}
                    for q in existing["verification_questions"]
                ]
                return InterventionAnalyzeResponse(
                    intervention_id=str(existing["_id"]),
                    tier=existing.get("tier"),
                    topic=existing.get("topic"),
                    initial_score=existing.get("initial_score", 0.0),
                    gap_concept=existing.get("gap_concept"),
                    intervention_type=existing.get("intervention_type"),
                    explanation=existing.get("explanation"),
                    worked_example=existing.get("worked_example"),
                    verification_questions=public_qs,
                )

        attempt = await self.attempts.latest_completed(
            quiz_id=request.quiz_id, student_id=request.student_id
        )

        questions = quiz.get("questions", [])
        total = len(questions)
        responses_db = (attempt or {}).get("responses", {})

        correct_count = 0
        wrong_questions: List[Dict[str, Any]] = []
        for q in questions:
            qid = q.get("qid")
            resp = responses_db.get(qid, {}) if isinstance(responses_db, dict) else {}
            if "is_correct" in resp:
                ok = bool(resp.get("is_correct"))
            else:
                ok = _is_correct(resp.get("answer"), q.get("correct"))
            if ok:
                correct_count += 1
            else:
                wrong_questions.append({
                    "question": q.get("question", ""),
                    "student_answer": resp.get("answer", "(blank)"),
                    "correct": q.get("correct", ""),
                })

        initial_score = round((correct_count / total * 100.0), 1) if total else 0.0
        tier = _tier_for(initial_score)

        now = datetime.utcnow().isoformat()
        try:
            daily_doc = await self.daily.get(request.daily_id)
        except InvalidObjectId:
            daily_doc = None
        date_str = daily_doc.get("date") if daily_doc else None

        base_record = {
            "student_id": request.student_id,
            "daily_id": request.daily_id,
            "quiz_id": request.quiz_id,
            "attempt_id": str(attempt["_id"]) if attempt else None,
            "date": date_str,
            "class_no": quiz.get("class_no"),
            "section": quiz.get("section"),
            "subject": quiz.get("subject"),
            "topic": quiz.get("topic"),
            "initial_score": initial_score,
            "tier": tier,
            "created_at": now,
        }

        # Mastered: no intervention, no LLM call, no student work
        if tier == "mastered":
            record = {
                **base_record,
                "gap_concept": None, "intervention_type": None, "explanation": None,
                "worked_example": None, "verification_questions": [],
                "verification_score": None, "learning_gain": None,
                "status": "mastered", "completed_at": now,
            }
            await self.interventions.upsert_by_keys(
                student_id=request.student_id, daily_id=request.daily_id,
                quiz_id=request.quiz_id, doc=record,
            )
            return InterventionAnalyzeResponse(
                intervention_id=None, tier="mastered", topic=quiz.get("topic"),
                initial_score=initial_score, verification_questions=[],
            )

        # Non-mastered: generate the targeted intervention
        content = await generate_intervention(
            wrong_questions=wrong_questions,
            topic=quiz.get("topic", quiz.get("subject", "this topic")),
            subject=quiz.get("subject", ""),
            class_no=quiz.get("class_no", 6),
            tier=tier,
        )

        record = {
            **base_record,
            "gap_concept": content["gap_concept"],
            "intervention_type": content["intervention_type"],
            "explanation": content["explanation"],
            "worked_example": content["worked_example"],
            "verification_questions": content["verification_questions"],
            "verification_score": None, "learning_gain": None,
            "status": "pending", "completed_at": None,
        }
        result = await self.interventions.upsert_by_keys(
            student_id=request.student_id, daily_id=request.daily_id,
            quiz_id=request.quiz_id, doc=record,
        )
        if result.upserted_id:
            intervention_id = str(result.upserted_id)
        else:
            existing = await self.interventions.find_existing(
                student_id=request.student_id, daily_id=request.daily_id, quiz_id=request.quiz_id)
            intervention_id = str(existing["_id"])

        public_qs = [
            {"qid": q["qid"], "question": q["question"],
             "question_type": q["question_type"], "difficulty": q["difficulty"],
             "options": q["options"]}
            for q in content["verification_questions"]
        ]

        return InterventionAnalyzeResponse(
            intervention_id=intervention_id,
            tier=tier,
            topic=quiz.get("topic"),
            initial_score=initial_score,
            gap_concept=content["gap_concept"],
            intervention_type=content["intervention_type"],
            explanation=content["explanation"],
            worked_example=content["worked_example"],
            verification_questions=public_qs,
        )

    async def verify(self, request: VerifyInterventionRequest, *,
                     requester: CurrentUser) -> VerifyInterventionResponse:
        record = await self.interventions.get(request.intervention_id)  # InvalidObjectId -> 400
        if not record:
            raise NotFoundError("Intervention not found")
        assert_can_access_student(requester, record.get("student_id"))

        vqs = record.get("verification_questions", [])
        total = len(vqs)
        correct_count = 0
        review: List[Dict[str, Any]] = []

        for q in vqs:
            qid = q.get("qid")
            student_resp = request.responses.get(qid, {}) if request.responses else {}
            student_answer = student_resp.get("answer") if isinstance(student_resp, dict) else student_resp
            ok = _is_correct(student_answer, q.get("correct"))
            if ok:
                correct_count += 1
            review.append({
                "qid": qid, "question": q.get("question"), "is_correct": ok,
                "your_answer": student_answer, "correct": q.get("correct"),
                "explanation": q.get("explanation"),
            })

        verification_score = round((correct_count / total * 100.0), 1) if total else 0.0
        initial_score = float(record.get("initial_score", 0.0))
        learning_gain = round(verification_score - initial_score, 1)
        status = "needs_teacher_support" if verification_score < SUPPORT_THRESHOLD else "improved"

        now = datetime.utcnow().isoformat()
        await self.interventions.update_one(
            {"_id": record["_id"]},
            {"$set": {
                "verification_score": verification_score,
                "learning_gain": learning_gain,
                "status": status,
                "verification_responses": request.responses,
                "completed_at": now,
            }},
        )

        return VerifyInterventionResponse(
            intervention_id=str(record["_id"]),
            initial_score=initial_score,
            verification_score=verification_score,
            learning_gain=learning_gain,
            status=status,
            review=review,
        )


def get_intervention_service(
    quizzes: QuizRepository = Depends(get_quiz_repo),
    daily: DailyClassRepository = Depends(get_daily_repo),
    attempts: QuizAttemptRepository = Depends(get_quiz_attempt_repo),
    interventions: InterventionRepository = Depends(get_intervention_repo),
) -> InterventionService:
    return InterventionService(quizzes, daily, attempts, interventions)
