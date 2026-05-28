"""
One-shot seed script: hand-authored Guru-Shishya demo stories.

Seeds two stories into the guru_shishya_stories collection so the demo
loads them instantly (no LLM call). Idempotent — re-runs upsert.

Targets:
  - Respiration in Organisms        → daily_id 6a18355dcc86cd345c96f5b7 (grade 7 Science)
  - Proper and Improper Fractions   → daily_id 6a0f2b7e62a6f3344b05f2d1 (grade 6 Maths)

Both stories obey the Guru-Shishya prompt's structural rules:
  - 4 scenes (normal / problem / aha / resolution)
  - Lines alternate guru ↔ shishya, scenes 0-2 start with guru, scene 3 starts with shishya
  - Concept name appears ONLY in concept_callout.term
  - Examples drawn strictly from a student's daily world
  - At least one funny moment per story

Usage:
    python seed_guru_stories.py
    STUDENT_ID=2345678 python seed_guru_stories.py   # to seed under a different student
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient


DEFAULT_STUDENT_ID = os.environ.get("STUDENT_ID", "1245372")
TENANT             = os.environ.get("TENANT", "demo-school")


# ─────────────────────────────────────────────────────────────────────────────
# Story 1 — Respiration in Organisms (Class 7 Science)
# ─────────────────────────────────────────────────────────────────────────────
RESPIRATION_STORY = {
    "personality_lens": "curious",
    "topic_slug": "respiration-in-organisms",
    "exchanges": [
        {
            "scene_index": 0,
            "scene_label": "The story begins",
            "scene_background": "normal",
            "lines": [
                {
                    "speaker": "guru",
                    "text": "Arrey Shishya. Why are you slumped like a wet kurta?",
                    "expression": "curious",
                    "sfx": None,
                },
                {
                    "speaker": "shishya",
                    "text": "Guruji, sports day was today. My legs are jelly.",
                    "expression": "worried",
                    "sfx": None,
                },
                {
                    "speaker": "guru",
                    "text": "Aha. Then sit. I want to ask you something.",
                    "expression": "happy",
                    "sfx": None,
                },
            ],
            "concept_callout": None,
        },
        {
            "scene_index": 1,
            "scene_label": "The interesting question",
            "scene_background": "problem",
            "lines": [
                {
                    "speaker": "guru",
                    "text": "After the 100 metres race. Your breathing. What was it doing?",
                    "expression": "curious",
                    "sfx": None,
                },
                {
                    "speaker": "shishya",
                    "text": "Like a steam engine, Guruji! Hu hu hu. Couldn't stop.",
                    "expression": "worried",
                    "sfx": "HMMMM...",
                },
                {
                    "speaker": "guru",
                    "text": "Why? You stopped running. Why keep panting?",
                    "expression": "curious",
                    "sfx": None,
                },
                {
                    "speaker": "shishya",
                    "text": "Because my lungs got tired? Needed extra air?",
                    "expression": "worried",
                    "sfx": None,
                },
                {
                    "speaker": "guru",
                    "text": "Tired? Lungs are not the ones running — you are.",
                    "expression": "curious",
                    "sfx": None,
                },
            ],
            "concept_callout": None,
        },
        {
            "scene_index": 2,
            "scene_label": "Why and how",
            "scene_background": "aha",
            "lines": [
                {
                    "speaker": "guru",
                    "text": "Picture tiny chefs inside every muscle of yours.",
                    "expression": "aha",
                    "sfx": "PING!",
                },
                {
                    "speaker": "shishya",
                    "text": "Chefs? Inside me? Cooking what?",
                    "expression": "shocked",
                    "sfx": None,
                },
                {
                    "speaker": "guru",
                    "text": "Energy. They burn the sugar from your tiffin.",
                    "expression": "happy",
                    "sfx": None,
                },
                {
                    "speaker": "shishya",
                    "text": "Burning! So they need air! Oxygen!",
                    "expression": "aha",
                    "sfx": None,
                },
                {
                    "speaker": "guru",
                    "text": "Hu hu hu — that was you delivering oxygen to chefs.",
                    "expression": "happy",
                    "sfx": None,
                },
            ],
            "concept_callout": {
                "emoji": "🫁",
                "term": "Respiration",
                "simple_definition": None,
                "precise_definition": (
                    "The chemical process in every living cell where glucose reacts "
                    "with oxygen to release the energy your body runs on."
                ),
                "teacher_line": (
                    "Your teacher said: every cell is busy burning glucose right now, "
                    "even as you sit reading."
                ),
                "formula": "Glucose + Oxygen → Energy + CO₂ + H₂O",
            },
        },
        {
            "scene_index": 3,
            "scene_label": "It lands",
            "scene_background": "resolution",
            "lines": [
                {
                    "speaker": "shishya",
                    "text": "So all that gasping was just oxygen for the chefs!",
                    "expression": "happy",
                    "sfx": None,
                },
                {
                    "speaker": "guru",
                    "text": "Exactly. Now eat tiffin. The chefs are unionising.",
                    "expression": "happy",
                    "sfx": "HA!",
                },
            ],
            "concept_callout": None,
        },
    ],
    "concept_highlights": [
        {
            "emoji": "🫁",
            "term": "Respiration",
            "one_line": "How your cells turn food into energy using oxygen.",
        },
        {
            "emoji": "🍞",
            "term": "Glucose",
            "one_line": "The fuel your tiffin gives the tiny chefs inside.",
        },
        {
            "emoji": "💨",
            "term": "Oxygen",
            "one_line": "The air that keeps every cell's chef cooking.",
        },
    ],
    "completion_message": "Guruji explained. Shishya understood. So did you.",
}


# ─────────────────────────────────────────────────────────────────────────────
# Story 2 — Proper and Improper Fractions (Class 6 Maths)
# ─────────────────────────────────────────────────────────────────────────────
FRACTIONS_STORY = {
    "personality_lens": "curious",
    "topic_slug": "proper-and-improper-fractions",
    "exchanges": [
        {
            "scene_index": 0,
            "scene_label": "The story begins",
            "scene_background": "normal",
            "lines": [
                {
                    "speaker": "guru",
                    "text": "Shishya. Came running. Mouth still chewing. What's the news?",
                    "expression": "curious",
                    "sfx": None,
                },
                {
                    "speaker": "shishya",
                    "text": "Guruji! Canteen pizza day! I got 5 slices!",
                    "expression": "happy",
                    "sfx": None,
                },
                {
                    "speaker": "guru",
                    "text": "5 slices? From one pizza? Greedy fellow.",
                    "expression": "curious",
                    "sfx": None,
                },
            ],
            "concept_callout": None,
        },
        {
            "scene_index": 1,
            "scene_label": "The interesting question",
            "scene_background": "problem",
            "lines": [
                {
                    "speaker": "guru",
                    "text": "Tell me. One pizza is cut into 4 slices, yes?",
                    "expression": "curious",
                    "sfx": None,
                },
                {
                    "speaker": "shishya",
                    "text": "Yes Guruji. Four equal pieces.",
                    "expression": "neutral",
                    "sfx": None,
                },
                {
                    "speaker": "guru",
                    "text": "And you ate 5 slices. So how much pizza?",
                    "expression": "curious",
                    "sfx": None,
                },
                {
                    "speaker": "shishya",
                    "text": "Five-by-four. But fractions are always less than one!",
                    "expression": "worried",
                    "sfx": "HMMMM...",
                },
                {
                    "speaker": "guru",
                    "text": "Then how did you eat 5 slices? Magic?",
                    "expression": "curious",
                    "sfx": None,
                },
            ],
            "concept_callout": None,
        },
        {
            "scene_index": 2,
            "scene_label": "Why and how",
            "scene_background": "aha",
            "lines": [
                {
                    "speaker": "guru",
                    "text": "Look. 4 slices was one full pizza. 5 is...",
                    "expression": "aha",
                    "sfx": "PING!",
                },
                {
                    "speaker": "shishya",
                    "text": "Wait. One full pizza PLUS one extra slice!",
                    "expression": "shocked",
                    "sfx": None,
                },
                {
                    "speaker": "guru",
                    "text": "Yes! Your 5/4 is more than one. Allowed.",
                    "expression": "happy",
                    "sfx": None,
                },
                {
                    "speaker": "shishya",
                    "text": "But it is still a fraction? Bigger than one?",
                    "expression": "curious",
                    "sfx": None,
                },
                {
                    "speaker": "guru",
                    "text": "Some fractions stay small, some grow big. Different names.",
                    "expression": "happy",
                    "sfx": None,
                },
            ],
            "concept_callout": {
                "emoji": "🍕",
                "term": "Proper and Improper Fractions",
                "simple_definition": (
                    "Proper: top number smaller than bottom — less than one whole. "
                    "Improper: top number equal or bigger — one whole or more."
                ),
                "precise_definition": (
                    "A proper fraction has numerator < denominator (value < 1). "
                    "An improper fraction has numerator ≥ denominator (value ≥ 1)."
                ),
                "teacher_line": (
                    "Your teacher said: when the top number beats the bottom number, "
                    "the fraction beats one whole."
                ),
                "formula": "Proper:  a/b  where a < b    |    Improper:  a/b  where a ≥ b",
            },
        },
        {
            "scene_index": 3,
            "scene_label": "It lands",
            "scene_background": "resolution",
            "lines": [
                {
                    "speaker": "shishya",
                    "text": "So 5/4 pizza meant I had more than one whole!",
                    "expression": "happy",
                    "sfx": None,
                },
                {
                    "speaker": "guru",
                    "text": "Yes. And next time — share with Guruji. Whole pizza.",
                    "expression": "happy",
                    "sfx": "HA!",
                },
            ],
            "concept_callout": None,
        },
    ],
    "concept_highlights": [
        {
            "emoji": "🍕",
            "term": "Proper Fraction",
            "one_line": "Top number smaller than bottom — less than one whole.",
        },
        {
            "emoji": "🍕🍕",
            "term": "Improper Fraction",
            "one_line": "Top number bigger or equal — one whole or more.",
        },
        {
            "emoji": "1️⃣",
            "term": "The Whole",
            "one_line": "The bottom number tells you how many slices make one.",
        },
    ],
    "completion_message": "Guruji explained. Shishya understood. So did you.",
}


# ─────────────────────────────────────────────────────────────────────────────
# Seed targets — (daily_id, grade, story)
# ─────────────────────────────────────────────────────────────────────────────
SEED_TARGETS = [
    ("6a18355dcc86cd345c96f5b7", 7, RESPIRATION_STORY),
    ("6a0f2b7e62a6f3344b05f2d1", 6, FRACTIONS_STORY),
]


def _resolve_mongo_uri_and_db() -> tuple[str, str]:
    uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI")
    db_name = os.environ.get("MONGODB_DB") or os.environ.get("MONGO_DB")
    if uri and db_name:
        return uri, db_name
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app.core.config import settings  # noqa: E402
    return (
        uri     or settings.MONGODB_URI,
        db_name or settings.MONGODB_DB,
    )


async def seed() -> None:
    uri, db_name = _resolve_mongo_uri_and_db()
    print(f"[seed_guru_stories] DB: {db_name}")
    print(f"[seed_guru_stories] Student: {DEFAULT_STUDENT_ID}, Tenant: {TENANT}")

    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    now = datetime.now(timezone.utc).isoformat()

    for daily_id, grade, story in SEED_TARGETS:
        doc = {
            "daily_id":      daily_id,
            "student_id":    DEFAULT_STUDENT_ID,
            "grade":         grade,
            "personality":   story["personality_lens"],
            "story":         story,
            "generated_at":  now,
            "generation_ms": 0,
            "tenant":        TENANT,
            "source":        "hand_authored_demo",
        }
        result = await db.guru_shishya_stories.replace_one(
            {"daily_id": daily_id, "student_id": DEFAULT_STUDENT_ID},
            doc,
            upsert=True,
        )
        action = "inserted" if result.upserted_id else "updated"
        print(
            f"  ✓ {action:>8s}: {story['topic_slug']:35s} "
            f"daily_id={daily_id} grade={grade}"
        )

    client.close()
    print("[seed_guru_stories] Done.")


if __name__ == "__main__":
    asyncio.run(seed())
