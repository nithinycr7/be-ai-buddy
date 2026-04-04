"""
Seed script: Load curriculum chapter gists into MongoDB -> curriculum_chapters collection.

Usage:
    python seed_curriculum.py                          # dry run (no DB write)
    python seed_curriculum.py --execute                # write to DB
    python seed_curriculum.py --file data/curriculum_class7_ncert.json --board NCERT --class 7 --execute

Re-run safe: uses upsert on chapter_key.
"""

import asyncio
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient
import certifi
from dotenv import load_dotenv
import os

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB  = os.getenv("MONGODB_DB", "mymedha_dev")

SUBJECT_MAP = {
    "english": "English",
    "maths":   "Maths",
    "science": "Science",
    "social":  "Social Science",
}


def parse_chapter_key(key: str) -> dict:
    """
    Parse keys like:
        english_gepr1_ch01  -> subject=English, book_code=gepr1, chapter_number=1
        maths_gegp1_ch03    -> subject=Maths,   book_code=gegp1, chapter_number=3
        social_gees1_ch04   -> subject=Social Science, book_code=gees1, chapter_number=4
    """
    parts = key.split("_")
    if len(parts) < 3:
        raise ValueError(f"Unexpected key format: {key}")

    raw_subject   = parts[0]
    book_code     = parts[1]
    chapter_part  = parts[2]                        # e.g. "ch01"

    subject = SUBJECT_MAP.get(raw_subject)
    if not subject:
        raise ValueError(f"Unknown subject prefix '{raw_subject}' in key '{key}'")

    match = re.search(r"\d+", chapter_part)
    if not match:
        raise ValueError(f"Cannot extract chapter number from '{chapter_part}' in key '{key}'")
    chapter_number = int(match.group())

    return {
        "subject":        subject,
        "book_code":      book_code,
        "chapter_number": chapter_number,
    }


def build_document(chapter_key: str, data: dict, board: str, class_no: int) -> dict:
    parsed = parse_chapter_key(chapter_key)
    now    = datetime.now(timezone.utc)

    return {
        "chapter_key":          chapter_key,
        "board":                board,
        "class":                class_no,
        "subject":              parsed["subject"],
        "book_code":            parsed["book_code"],
        "chapter_number":       parsed["chapter_number"],
        "chapter_title":        data.get("chapter_title", ""),
        "learning_objectives":  data.get("learning_objectives", []),
        "concepts":             data.get("concepts", []),
        "chapter_summary":      data.get("chapter_summary", ""),
        "key_formulas_or_rules":data.get("key_formulas_or_rules", []),
        "real_world_connections":data.get("real_world_connections", []),
        "exercises_preserved":  data.get("exercises_preserved", []),
        "activities_preserved": data.get("activities_preserved", []),
        "created_at":           now,
        "updated_at":           now,
    }


async def run(file_path: str, board: str, class_no: int, execute: bool):
    raw = Path(file_path).read_text(encoding="utf-8")
    chapters: dict = json.loads(raw)

    docs = []
    for key, data in chapters.items():
        try:
            doc = build_document(key, data, board, class_no)
            docs.append(doc)
        except ValueError as e:
            print(f"  [SKIP] {e}")

    print(f"\nParsed {len(docs)} documents from '{file_path}'")
    print(f"  board={board}  class={class_no}\n")

    for d in docs:
        print(f"  {d['chapter_key']:30s}  subject={d['subject']:15s}  ch={d['chapter_number']}")

    if not execute:
        print("\n[DRY RUN] No data written. Pass --execute to write to DB.")
        return

    client = AsyncIOMotorClient(MONGODB_URI, tls=True, tlsCAFile=certifi.where())
    db     = client[MONGODB_DB]
    col    = db["curriculum_chapters"]

    inserted = 0
    updated  = 0

    for doc in docs:
        key = doc["chapter_key"]
        result = await col.update_one(
            {"chapter_key": key},
            {
                "$set":         {k: v for k, v in doc.items() if k != "created_at"},
                "$setOnInsert": {"created_at": doc["created_at"]},
            },
            upsert=True,
        )
        if result.upserted_id:
            inserted += 1
            print(f"  [INSERT] {key}")
        else:
            updated += 1
            print(f"  [UPDATE] {key}")

    client.close()
    print(f"\nDone. inserted={inserted}  updated={updated}  total={inserted + updated}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed curriculum chapters into MongoDB")
    parser.add_argument("--file",    default="data/curriculum_class7_ncert.json", help="Path to JSON file")
    parser.add_argument("--board",   default="NCERT",  help="Board name (e.g. NCERT, CBSE, ICSE)")
    parser.add_argument("--class",   dest="class_no", type=int, default=7, help="Class number")
    parser.add_argument("--execute", action="store_true", help="Write to DB (default is dry run)")
    args = parser.parse_args()

    asyncio.run(run(args.file, args.board, args.class_no, args.execute))
