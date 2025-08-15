from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict
from datetime import date
from ..core.security import api_key_guard
from ..db.mongo import get_db
from ..models.schemas import Quiz, QuizQuestion, QuizOption, QuizResponse
from ..services.ai import generate_quiz

router = APIRouter(prefix="/quizzes", tags=["quizzes"], dependencies=[Depends(api_key_guard)])

@router.post("/from-daily/{daily_id}", response_model=Quiz, status_code=201)
async def create_quiz_from_daily(daily_id: str):
    db = await get_db()
    d = await db.classes_daily.find_one({"_id":{"$oid": daily_id}})
    if not d:
        raise HTTPException(status_code=404, detail="Daily class not found")
    base = d.get("summary") or ""
    if not base:
        t = await db.transcripts.find_one({"daily_id": daily_id})
        base = t.get("text","") if t else ""
    qs = await generate_quiz(base, n_questions=5)
    questions = [QuizQuestion(qid=q["qid"], question=q["question"], options=[QuizOption(**o) for o in q["options"]], correct=q.get("correct",[])) for q in qs]
    quiz = Quiz(
        daily_id=daily_id,
        class_no=d["class_no"],
        section=d["section"],
        subject=d["subject"],
        topic_tags=d.get("topics", []),
        questions=questions
    )
    res = await db.quizzes.insert_one(quiz.model_dump(by_alias=True, exclude_none=True))
    quiz.id = str(res.inserted_id)
    return quiz

@router.post("/{quiz_id}/responses", response_model=QuizResponse, status_code=201)
async def submit_response(quiz_id: str, payload: Dict[str, List[str]], student_id: str):
    # payload = {"q1":["a"], "q2":["b"], ...}
    db = await get_db()
    quiz = await db.quizzes.find_one({"_id":{"$oid": quiz_id}})
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    # grade
    corr = {q["qid"]: set(q.get("correct", [])) for q in quiz["questions"]}
    total = len(corr) or 1
    score = 0
    for qid, gold in corr.items():
        pred = set(payload.get(qid, []))
        if pred == gold:
            score += 1
    pct = score / total
    # insert
    d = await db.classes_daily.find_one({"_id":{"$oid": quiz["daily_id"]}}) if quiz.get("daily_id") else None
    resp_doc = {
        "quiz_id": quiz_id,
        "daily_id": quiz.get("daily_id"),
        "student_id": student_id,
        "date": str(date.today()),
        "responses": payload,
        "score": pct
    }
    res = await db.quiz_responses.insert_one(resp_doc)
    return QuizResponse(id=str(res.inserted_id), **resp_doc)
