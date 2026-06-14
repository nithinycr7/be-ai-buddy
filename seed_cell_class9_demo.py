"""
Seed: Cell - Structure and Functions onto the LIVE demo student context.

The demo student logs in as Class 9 / Section A and the dashboard's active
date is 2026-06-01 (where "Internal Energy" already shows). This adds a
Biology card for the Cell topic on that exact context so it appears right
next to Internal Energy for the account you're already testing with.

The Explore-tab simulation is topic-driven (not class-driven), so the
scale-world (nucleus + orbiting organelles) still generates correctly.

Idempotent — safe to run multiple times.

    cd mymedha-lxp-be
    source venv/bin/activate
    python seed_cell_class9_demo.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.core.config import settings  # noqa: E402

FILTER = {
    "tenant":   "demo-school",
    "class_no": 9,
    "section":  "A",
    "date":     "2026-06-01",
    "subject":  "Biology",
}
TOPIC = "Cell - Structure and Functions"


async def seed() -> int:
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB]

    doc = {**FILTER, "topics": [TOPIC], "summary": None, "summary_blocks": []}
    res = await db.classes_daily.update_one(FILTER, {"$set": doc}, upsert=True)
    client.close()

    if res.upserted_id:
        print(f"Inserted  → _id={res.upserted_id}")
    elif res.modified_count:
        print("Updated   → existing Biology card refreshed.")
    else:
        print("No-op     → already present.")

    print()
    print("Refresh the Class 9 student dashboard (June 1st) → a new BIOLOGY card")
    print(f"'{TOPIC}' appears next to Internal Energy. Open it → Explore tab.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(seed()))
