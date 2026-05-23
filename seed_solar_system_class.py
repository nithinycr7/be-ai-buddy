"""
One-shot seed script: add a Solar System class to the dashboard.

Reads tenant / section / date from an existing class_no=7 daily-class doc so
that it lands on the same dashboard date as Photosynthesis, Fractions and
Heat-vs-Temperature. Idempotent — re-running it just upserts.

Usage:
    python seed_solar_system_class.py

The MongoDB URI is taken from MONGO_URI env var if set, otherwise from
app.core.config.settings (same source the running backend uses).
"""
from __future__ import annotations

import asyncio
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient


SUBJECT = "Science"
TOPIC   = "Solar System"
CLASS_NO = 7


def _resolve_mongo_uri_and_db() -> tuple[str, str]:
    uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI")
    db_name = os.environ.get("MONGODB_DB") or os.environ.get("MONGO_DB")
    if uri and db_name:
        return uri, db_name
    # Fall back to the backend's own config so we hit the same database
    # the running server uses.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app.core.config import settings  # noqa: E402
    return (
        uri     or settings.MONGODB_URI,
        db_name or settings.MONGODB_DB,
    )


async def seed() -> int:
    uri, db_name = _resolve_mongo_uri_and_db()
    print(f"🔗 Connecting to {db_name}…")
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    # Find one existing class_no=7 doc to crib tenant/section/date from.
    sample = await db.classes_daily.find_one(
        {"class_no": CLASS_NO},
        sort=[("date", -1)],
    )
    if not sample:
        print(
            f"❌ No existing class_no={CLASS_NO} record found in classes_daily. "
            f"Seed Photosynthesis (or any class for class 7) first, then re-run."
        )
        client.close()
        return 1

    tenant  = sample["tenant"]
    section = sample["section"]
    date    = sample["date"]
    print(
        f"📚 Mirroring existing record: tenant={tenant}, "
        f"section={section}, date={date}"
    )

    # Idempotent upsert keyed on (tenant, class_no, section, subject, date).
    # Matches the test-summary endpoint's key shape so we don't collide.
    result = await db.classes_daily.update_one(
        {
            "tenant":   tenant,
            "class_no": CLASS_NO,
            "section":  section,
            "subject":  SUBJECT,
            "date":     date,
            "topics":   [TOPIC],
        },
        {"$set": {
            "tenant":   tenant,
            "class_no": CLASS_NO,
            "section":  section,
            "subject":  SUBJECT,
            "date":     date,
            "topics":   [TOPIC],
        }},
        upsert=True,
    )

    if result.upserted_id:
        print(f"✅ Inserted Solar System class: _id={result.upserted_id}")
    elif result.modified_count:
        print("✅ Updated existing Solar System class.")
    else:
        print("ℹ️  Solar System class already present — nothing to change.")

    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(seed()))
