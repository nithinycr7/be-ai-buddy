"""
Integration test for the LIVE daily-quiz submit path after its migration onto the
repository layer. Drives the real `submit_daily_quiz` handler through repo instances
and asserts the scoring / XP / streak math + DB side-effects are preserved, plus
tenant isolation.

Requires a Mongo connection; runs against a throwaway DB so it never touches prod:
    MONGODB_DB=mymedha_repo_test ./venv/bin/python -m tests.test_daily_quiz_submit
Exits non-zero on any failure.
"""
import asyncio
import os
import sys
import types

os.environ.setdefault("MONGODB_DB", "mymedha_repo_test")

from bson import ObjectId  # noqa: E402

from app.db.mongo import get_db  # noqa: E402
from app.db.repositories import (  # noqa: E402
    DailyClassRepository, QuizAnalyticsRepository, QuizAttemptRepository,
    QuizRepository, StreakRepository, StudentDailyProgressRepository,
)
from app.services.daily_quiz_service import DailyQuizService  # noqa: E402

TENANT = "T1"
STUDENT = "STU-1"
COLLECTIONS = ("classes_daily", "quizzes", "student_quiz_attempts",
               "student_daily_progress", "streak_tracking", "quiz_analytics")


async def _run():
    db = await get_db()
    for c in COLLECTIONS:
        await db[c].delete_many({})

    daily_oid, quiz_oid = ObjectId(), ObjectId()
    await db.classes_daily.insert_one({"_id": daily_oid, "tenant": TENANT, "date": "2026-07-04",
        "class_no": 7, "section": "A", "subject": "Science"})
    # quizzes store daily_id as an ObjectId (AutoQuizGenerator's live shape)
    await db.quizzes.insert_one({"_id": quiz_oid, "tenant": TENANT, "daily_id": daily_oid,
        "questions": [{"qid": "q1", "difficulty": "easy", "correct": ["a"]},
                      {"qid": "q2", "difficulty": "hard", "correct": ["b"]}]})

    def service(tenant=TENANT):
        # generator is unused by submit() -> None is fine for this test
        return DailyQuizService(
            QuizRepository(db, tenant), DailyClassRepository(db, tenant),
            QuizAttemptRepository(db, tenant), StudentDailyProgressRepository(db, tenant),
            StreakRepository(db, tenant), QuizAnalyticsRepository(db, tenant), None)

    user = types.SimpleNamespace(role="student", student_id=STUDENT, kids=[])
    submit_args = dict(quiz_id=str(quiz_oid), daily_id=str(daily_oid), student_id=STUDENT,
        responses={"q1": {"answer": "a", "is_correct": True, "hint_used": False, "time_spent": 5},
                   "q2": {"answer": "b", "is_correct": True, "hint_used": False, "time_spent": 5}},
        time_taken_seconds=10)

    checks = []

    # Both correct, 1st attempt: weighted (1*1 + 3*1)/(1+3)*80 = 80.0
    # xp = 20 base + 10 no-hint + 6 speed = 36
    r = await service().submit(requester=user, **submit_args)
    checks += [
        ("score == 80.0", r["score"] == 80.0),
        ("correct_count == 2", r["correct_count"] == 2),
        ("xp_earned == 36", r["xp_earned"] == 36),
        ("current_streak == 1", r["current_streak"] == 1),
    ]

    prog = await db.student_daily_progress.find_one({"student_id": STUDENT, "daily_id": str(daily_oid)})
    checks += [
        ("progress quiz_score 80", bool(prog) and prog["quiz_score"] == 80.0),
        ("progress total_score 80", bool(prog) and prog["total_score"] == 80.0),
        ("progress is_complete True", bool(prog) and prog["is_complete"] is True),
    ]
    att = await db.student_quiz_attempts.find_one({"student_id": STUDENT})
    checks.append(("attempt completed + tenant-stamped",
                   bool(att) and att.get("completed_at") and att.get("tenant") == TENANT))
    strk = await db.streak_tracking.find_one({"student_id": STUDENT})
    checks.append(("streak total_xp 36, current 1",
                   bool(strk) and strk["total_xp"] == 36 and strk["current_streak"] == 1))
    checks.append(("analytics rows == 2",
                   await db.quiz_analytics.count_documents({"quiz_id": str(quiz_oid)}) == 2))

    # 2nd submit same day: streak must NOT double-increment; attempts -> 2
    r2 = await service().submit(requester=user, **submit_args)
    checks.append(("2nd submit same-day streak stays 1", r2["current_streak"] == 1))
    prog2 = await db.student_daily_progress.find_one({"student_id": STUDENT, "daily_id": str(daily_oid)})
    checks.append(("progress quiz_attempts == 2", bool(prog2) and prog2.get("quiz_attempts") == 2))

    # cross-tenant isolation: another tenant's service can't see this quiz -> domain NotFoundError (404)
    from app.core.exceptions import NotFoundError
    try:
        await service(tenant="OTHER").submit(requester=user, **submit_args)
        checks.append(("cross-tenant quiz -> NotFound(404)", False))
    except NotFoundError as e:
        checks.append(("cross-tenant quiz -> NotFound(404)", e.status_code == 404))

    for c in COLLECTIONS:
        await db[c].delete_many({})

    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    passed = all(ok for _, ok in checks)
    print("\nRESULT:", "ALL PASS" if passed else "FAILURES")
    return passed


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(_run()) else 1)
