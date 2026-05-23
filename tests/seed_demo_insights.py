"""
Seed demo data for the Class Insights view.

Populates:
  - students collection: 14 students for Class 7, Section B (Indian names)
  - student_daily_progress: 14 students x 3 dates x 2 subjects = 84 progress rows
    with a realistic score distribution (mastered / on-track / average / weak / not submitted)

Idempotent: upsert by (student_id) for students and
(student_id, date, subject) for progress.

Usage:
    venv/bin/python tests/seed_demo_insights.py            # dry run
    venv/bin/python tests/seed_demo_insights.py --execute  # write to DB
"""
import argparse
import asyncio
import os
import random
from datetime import datetime, timezone

import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

CLASS_NO = 7
SECTION = "B"
TENANT = "demo-school"
SCHOOL_ID = "demo-school"
SUBJECTS = ["Maths", "Science"]
DATES = ["2026-05-22", "2026-05-23", "2026-05-24"]  # yesterday, today, tomorrow

# Buckets keep scores within a band for each student so the same student
# is consistently weak / strong across days.
# (name, roll_no, bucket) — bucket gives the score range and read habits
STUDENTS = [
    ("Diya Singh",      "01", "mastered"),
    ("Aarav Sharma",    "02", "mastered"),
    ("Ananya Patel",    "03", "on_track"),
    ("Saanvi Iyer",     "04", "on_track"),
    ("Arjun Nair",      "05", "on_track"),
    ("Aditya Gupta",    "06", "on_track"),
    ("Aanya Bose",      "07", "on_track"),
    ("Myra Joshi",      "08", "average"),
    ("Riya Kapoor",     "09", "average"),
    ("Vivaan Khan",     "10", "average"),
    ("Vihaan Mehta",    "11", "weak"),
    ("Kabir Verma",     "12", "weak"),
    ("Ishaan Reddy",    "13", "absent"),
    ("Reyansh Pillai",  "14", "absent"),
]

# bucket -> (score_range, summary_prob, story_prob)
BUCKETS = {
    "mastered": ((88, 98), 1.0, 0.95),
    "on_track": ((70, 84), 0.95, 0.75),
    "average":  ((52, 68), 0.85, 0.45),
    "weak":     ((32, 49), 0.55, 0.20),
    "absent":   ((0, 0),   0.30, 0.05),  # didn't submit quiz, may still browse
}


def make_student_doc(name: str, roll_no: str) -> dict:
    student_id = f"demo-c{CLASS_NO}{SECTION.lower()}-r{roll_no}"
    return {
        "student_id": student_id,
        "roll_no": roll_no,
        "name": name,
        "class_no": CLASS_NO,
        "section": SECTION,
        "tenant": TENANT,
        "school_id": SCHOOL_ID,
        "demo_seed": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def make_progress_doc(student: dict, date: str, subject: str, rng: random.Random) -> dict:
    bucket = student["_bucket"]
    score_range, summary_prob, story_prob = BUCKETS[bucket]
    quiz_taken = bucket != "absent"
    quiz_score = rng.randint(*score_range) if quiz_taken else 0
    return {
        "student_id": student["student_id"],
        "class_no": CLASS_NO,
        "section": SECTION,
        "subject": subject,
        "date": date,
        "tenant": TENANT,
        "school_id": SCHOOL_ID,
        "summary_viewed": rng.random() < summary_prob,
        "story_generated": rng.random() < story_prob,
        "quiz_taken": quiz_taken,
        "quiz_latest_score": quiz_score,
        "total_score": quiz_score,
        "demo_seed": True,
        "updated_at": datetime.now(timezone.utc),
    }


async def run(execute: bool):
    student_docs = []
    for name, roll, bucket in STUDENTS:
        s = make_student_doc(name, roll)
        s["_bucket"] = bucket
        student_docs.append(s)

    progress_docs = []
    # Stable seed so re-runs produce the same numbers.
    rng = random.Random(42)
    for date in DATES:
        for student in student_docs:
            for subject in SUBJECTS:
                progress_docs.append(make_progress_doc(student, date, subject, rng))

    print(f"Students: {len(student_docs)}  Progress rows: {len(progress_docs)}")
    print(f"  Class {CLASS_NO}-{SECTION}  Subjects: {SUBJECTS}  Dates: {DATES}")
    by_bucket = {}
    for s in STUDENTS:
        by_bucket.setdefault(s[2], 0)
        by_bucket[s[2]] += 1
    print(f"  Bucket mix: {by_bucket}")

    if not execute:
        print("\n[DRY RUN] Pass --execute to write to DB.")
        return

    client = AsyncIOMotorClient(os.getenv("MONGODB_URI"), tls=True, tlsCAFile=certifi.where())
    db = client[os.getenv("MONGODB_DB", "mymedha_dev")]

    # Upsert students
    students_col = db.students
    students_inserted = students_updated = 0
    for s in student_docs:
        doc = {k: v for k, v in s.items() if k != "_bucket"}
        res = await students_col.update_one(
            {"student_id": doc["student_id"]},
            {"$set": {k: v for k, v in doc.items() if k != "created_at"},
             "$setOnInsert": {"created_at": doc["created_at"]}},
            upsert=True,
        )
        if res.upserted_id:
            students_inserted += 1
        else:
            students_updated += 1
    print(f"\nstudents: inserted={students_inserted} updated={students_updated}")

    # Upsert progress
    progress_col = db.student_daily_progress
    progress_inserted = progress_updated = 0
    for p in progress_docs:
        res = await progress_col.update_one(
            {"student_id": p["student_id"], "date": p["date"], "subject": p["subject"]},
            {"$set": p},
            upsert=True,
        )
        if res.upserted_id:
            progress_inserted += 1
        else:
            progress_updated += 1
    print(f"student_daily_progress: inserted={progress_inserted} updated={progress_updated}")

    client.close()
    print("\nDone.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="Write to DB (default: dry run)")
    args = ap.parse_args()
    asyncio.run(run(args.execute))
