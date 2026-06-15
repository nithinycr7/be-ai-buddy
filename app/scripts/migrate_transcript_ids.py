"""
Migrate daily_transcripts docs that were inserted with an auto ObjectId `_id`
to the canonical worker convention: {schoolId}_{classId}_{subject}_{timestamp}.

`_id` is immutable in Mongo, so each doc is re-inserted under the correct string
`_id` and the old ObjectId doc is deleted. Idempotent + safe:
  • only ObjectId-keyed docs are touched (string _ids are already correct)
  • timestamp derived from `timestamp` → `createdAt` → the ObjectId's own time
  • if the target string _id already exists, the old doc is just deleted

Usage:
    python -m app.scripts.migrate_transcript_ids --dry-run   # show the plan
    python -m app.scripts.migrate_transcript_ids             # execute
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from bson import ObjectId

from app.db.mongo import get_client
from app.services.summary_blocks import make_daily_transcript_id


def _derive_timestamp(doc: dict) -> int:
    ts = doc.get("timestamp")
    if isinstance(ts, (int, float)) and ts > 0:
        return int(ts)
    ca = doc.get("createdAt")
    if ca:
        try:
            dt = ca if isinstance(ca, datetime) else datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
            return int(dt.timestamp())
        except Exception:
            pass
    # fall back to the time encoded in the ObjectId itself
    if isinstance(doc.get("_id"), ObjectId):
        return int(doc["_id"].generation_time.timestamp())
    return int(datetime.utcnow().timestamp())


async def _run(dry_run: bool) -> None:
    coll = get_client()["mymedha_dev"].daily_transcripts
    migrated = skipped = 0

    async for doc in coll.find({}):
        if not isinstance(doc["_id"], ObjectId):
            continue  # already a proper string _id
        ts = _derive_timestamp(doc)
        new_id = make_daily_transcript_id(
            doc.get("schoolId", "unknown"), doc.get("classId", "unknown"),
            doc.get("subject", "unknown"), ts,
        )
        print(f"{'[dry-run] ' if dry_run else ''}{doc['_id']}  ->  {new_id}")
        if dry_run:
            migrated += 1
            continue

        target_exists = await coll.find_one({"_id": new_id}, {"_id": 1})
        if not target_exists:
            new_doc = {**doc, "_id": new_id, "timestamp": ts}
            await coll.insert_one(new_doc)
        else:
            print(f"    target {new_id} already exists — removing old ObjectId doc only")
        await coll.delete_one({"_id": doc["_id"]})
        migrated += 1

    print(f"\n{'Would migrate' if dry_run else 'Migrated'}: {migrated} | skipped (already string): {skipped}")


def main() -> None:
    p = argparse.ArgumentParser(description="Migrate ObjectId daily_transcripts _ids to the worker convention.")
    p.add_argument("--dry-run", action="store_true", help="show the plan without changing anything")
    asyncio.run(_run(p.parse_args().dry_run))


if __name__ == "__main__":
    main()
