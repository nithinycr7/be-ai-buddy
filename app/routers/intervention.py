"""
Adaptive Intervention API
=========================
Back half of the learning loop:
  Quiz -> Analysis Engine -> Gap Detection -> Micro Intervention -> Verification

Self-contained module. Reads the student's stored quiz attempt, runs 3-tier
analysis, and (for non-mastered students only) generates + scores a short
targeted intervention. Records land in the `student_interventions` collection
which the teacher dashboard reads.
"""
from datetime import datetime
from typing import Any, Dict, List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from ..models.schemas import (
    AnalyzeInterventionRequest,
    InterventionAnalyzeResponse,
    VerifyInterventionRequest,
    VerifyInterventionResponse,
)
from ..services.intervention_engine import generate_intervention

router = APIRouter(prefix="/intervention", tags=["intervention"],
                   dependencies=[Depends(api_key_guard)])

# 3-tier thresholds (mastery %, 0-100)
MASTERED_THRESHOLD = 80.0
PREREQUISITE_THRESHOLD = 40.0
# verification outcome
SUPPORT_THRESHOLD = 50.0  # below this after intervention -> needs teacher support


def _normalize_answer(value: Any) -> set:
    """Normalize an MCQ/text answer to a comparable lowercase set."""
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


@router.post("/analyze", response_model=InterventionAnalyzeResponse)
async def analyze(request: AnalyzeInterventionRequest,
                  tenant: str = Depends(get_tenant)):
    """Analyse the latest quiz attempt; mastered students get a no-op response,
    everyone else gets a generated micro-intervention + 3 verification questions."""
    db = await get_db()

    quiz = await db.quizzes.find_one({"_id": ObjectId(request.quiz_id), "tenant": tenant})
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    # Idempotent: if we already analysed this (student, daily, quiz), reuse it
    # rather than regenerating (avoids LLM cost and never wipes a finished record).
    existing = await db.student_interventions.find_one({
        "student_id": request.student_id,
        "daily_id": request.daily_id,
        "quiz_id": request.quiz_id,
        "tenant": tenant,
    })
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

    # Latest completed attempt for this student on this quiz
    attempt = await db.student_quiz_attempts.find_one(
        {
            "quiz_id": request.quiz_id,
            "student_id": request.student_id,
            "completed_at": {"$ne": None},
            "tenant": tenant,
        },
        sort=[("completed_at", -1)],
    )

    questions = quiz.get("questions", [])
    total = len(questions)
    responses_db = (attempt or {}).get("responses", {})

    # Compute mastery % (0-100) and collect wrong questions
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
    daily = await db.classes_daily.find_one({"_id": ObjectId(request.daily_id), "tenant": tenant})
    date_str = daily.get("date") if daily else None

    base_record = {
        "student_id": request.student_id,
        "daily_id": request.daily_id,
        "quiz_id": request.quiz_id,
        "attempt_id": str(attempt["_id"]) if attempt else None,
        "tenant": tenant,
        "date": date_str,
        "class_no": quiz.get("class_no"),
        "section": quiz.get("section"),
        "subject": quiz.get("subject"),
        "topic": quiz.get("topic"),
        "initial_score": initial_score,
        "tier": tier,
        "created_at": now,
    }

    # ── Mastered: no intervention, no LLM call, no student work ───────────────
    if tier == "mastered":
        record = {
            **base_record,
            "gap_concept": None,
            "intervention_type": None,
            "explanation": None,
            "worked_example": None,
            "verification_questions": [],
            "verification_score": None,
            "learning_gain": None,
            "status": "mastered",
            "completed_at": now,
        }
        await db.student_interventions.update_one(
            {"student_id": request.student_id, "daily_id": request.daily_id,
             "quiz_id": request.quiz_id},
            {"$set": record}, upsert=True,
        )
        return InterventionAnalyzeResponse(
            intervention_id=None, tier="mastered", topic=quiz.get("topic"),
            initial_score=initial_score, verification_questions=[],
        )

    # ── Non-mastered: generate the targeted intervention ──────────────────────
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
        "verification_score": None,
        "learning_gain": None,
        "status": "pending",
        "completed_at": None,
    }
    result = await db.student_interventions.update_one(
        {"student_id": request.student_id, "daily_id": request.daily_id,
         "quiz_id": request.quiz_id},
        {"$set": record}, upsert=True,
    )
    if result.upserted_id:
        intervention_id = str(result.upserted_id)
    else:
        existing = await db.student_interventions.find_one(
            {"student_id": request.student_id, "daily_id": request.daily_id,
             "quiz_id": request.quiz_id, "tenant": tenant})
        intervention_id = str(existing["_id"])

    # Public verification questions (strip the answers)
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


@router.post("/verify", response_model=VerifyInterventionResponse)
async def verify(request: VerifyInterventionRequest,
                 tenant: str = Depends(get_tenant)):
    """Score the verification questions and compute the learning gain."""
    db = await get_db()

    record = await db.student_interventions.find_one(
        {"_id": ObjectId(request.intervention_id), "tenant": tenant})
    if not record:
        raise HTTPException(status_code=404, detail="Intervention not found")

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
            "qid": qid,
            "question": q.get("question"),
            "is_correct": ok,
            "your_answer": student_answer,
            "correct": q.get("correct"),
            "explanation": q.get("explanation"),
        })

    verification_score = round((correct_count / total * 100.0), 1) if total else 0.0
    initial_score = float(record.get("initial_score", 0.0))
    learning_gain = round(verification_score - initial_score, 1)
    status = "needs_teacher_support" if verification_score < SUPPORT_THRESHOLD else "improved"

    now = datetime.utcnow().isoformat()
    await db.student_interventions.update_one(
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
