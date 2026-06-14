"""
Seed: Class 8 Science — "Cell - Structure and Functions"

Adds a classes_daily record so the student dashboard shows this class
for Class 8 Section A. The Explore tab will then call /api/engine/config
which generates the simulation (scale world: nucleus + orbiting organelles).

Works by piggybacking on the same tenant/section/date as any existing
classes_daily record. Idempotent — safe to run multiple times.

Usage:
    cd mymedha-lxp-be
    python seed_cell_structure_class8.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date

from motor.motor_asyncio import AsyncIOMotorClient


SUBJECT  = "Science"
TOPIC    = "Cell - Structure and Functions"
CLASS_NO = 8


def _resolve_mongo() -> tuple[str, str]:
    uri     = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI")
    db_name = os.environ.get("MONGODB_DB")  or os.environ.get("MONGO_DB")
    if uri and db_name:
        return uri, db_name
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app.core.config import settings  # noqa: E402
    return (uri or settings.MONGODB_URI, db_name or settings.MONGODB_DB)


async def seed() -> int:
    uri, db_name = _resolve_mongo()
    print(f"Connecting to {db_name}…")
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    # --- find tenant / section / date to anchor the new record -------------
    # 1. Prefer an existing Class 8 record (keeps section + date consistent)
    sample = await db.classes_daily.find_one(
        {"class_no": CLASS_NO},
        sort=[("date", -1)],
    )

    # 2. Fall back to Class 7 (matches the other demo seeds)
    if not sample:
        sample = await db.classes_daily.find_one(
            {"class_no": 7},
            sort=[("date", -1)],
        )

    # 3. Last resort: any record in the collection
    if not sample:
        sample = await db.classes_daily.find_one({}, sort=[("date", -1)])

    if sample:
        tenant  = sample.get("tenant",  "demo-school")
        section = sample.get("section", "A")
        date_str = sample.get("date")
        # date field may be a Python date or an ISO string
        if isinstance(date_str, date):
            date_str = date_str.isoformat()
        elif date_str is None:
            date_str = date.today().isoformat()
        print(f"Anchoring to: tenant={tenant}, section={section}, date={date_str}")
    else:
        # Fresh database — use safe defaults
        tenant   = "demo-school"
        section  = "A"
        date_str = date.today().isoformat()
        print(f"No existing records found — using defaults: {tenant}/{section}/{date_str}")

    # --- upsert ------------------------------------------------------------
    filter_doc = {
        "tenant":   tenant,
        "class_no": CLASS_NO,
        "section":  section,
        "subject":  SUBJECT,
        "date":     date_str,
    }
    set_doc = {
        **filter_doc,
        "topics": [TOPIC],
    }

    result = await db.classes_daily.update_one(
        filter_doc,
        {"$set": set_doc},
        upsert=True,
    )

    client.close()

    if result.upserted_id:
        print(f"Inserted  → _id={result.upserted_id}")
    elif result.modified_count:
        print("Updated   → existing record refreshed.")
    else:
        print("No-op     → record already present, nothing changed.")

    print()
    print("What happens next:")
    print(f"  1. Open the student dashboard as a Class {CLASS_NO} student.")
    print(f"  2. You should see '{TOPIC}' under {SUBJECT}.")
    print(f"  3. Click the class → switch to the Explore tab.")
    print(f"  4. The engine calls /api/engine/config → Gemini generates the")
    print(f"     scale world (nucleus as central body, organelles orbiting).")
    print(f"     First load takes ~5s; subsequent loads are cached.")
    print()
    print("To force-regenerate after changing the prompt, click the ↻ button")
    print("in the top-right of the Explore tab.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(seed()))
