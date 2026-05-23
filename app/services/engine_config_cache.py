"""
MongoDB cache layer for AI-generated engine world configs.

Reuses the existing async Mongo connection from app.db.mongo.get_db().
Stores one document per (topic_slug, grade) pair in `engine_configs`.

Cache is invalidated automatically when CURRENT_PROMPT_VERSION changes
— older records are treated as stale and regenerated on next request.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pymongo import ASCENDING

from app.db.mongo import get_db

CURRENT_PROMPT_VERSION = "v4"
# Bump this when prompts/engine_prompt.txt changes — every existing
# record with an older version will be treated as a cache miss.

COLLECTION_NAME = "engine_configs"

_index_ready = False


async def _get_collection():
    """Return the engine_configs collection, ensuring its unique index exists.

    The index check is idempotent in MongoDB but we still gate it behind a
    module-level flag so we don't issue the call on every cache lookup.
    """
    global _index_ready
    db = await get_db()
    collection = db[COLLECTION_NAME]

    if not _index_ready:
        await collection.create_index(
            [("topic_slug", ASCENDING), ("grade", ASCENDING)],
            unique=True,
            name="topic_grade_unique",
        )
        _index_ready = True

    return collection


async def get_cached_config(topic_slug: str, grade: int) -> Optional[dict]:
    """Return the cached config dict, or None on miss / stale prompt version."""
    collection = await _get_collection()

    doc = await collection.find_one(
        {"topic_slug": topic_slug, "grade": grade},
        {"_id": 0},
    )
    if not doc:
        return None

    if doc.get("prompt_version") != CURRENT_PROMPT_VERSION:
        return None

    return doc["config"]


async def save_config(
    topic_slug: str,
    grade: int,
    config: dict,
    generation_ms: int,
    gemini_model: str,
    force: bool = False,
) -> datetime:
    """Upsert a config record. Returns the generated_at timestamp."""
    collection = await _get_collection()

    now = datetime.now(timezone.utc)
    doc = {
        "topic_slug":           topic_slug,
        "grade":                grade,
        "config":               config,
        "generated_at":         now,
        "generation_ms":        generation_ms,
        "gemini_model":         gemini_model,
        "prompt_version":       CURRENT_PROMPT_VERSION,
        "force_regenerated_at": now if force else None,
    }

    await collection.replace_one(
        {"topic_slug": topic_slug, "grade": grade},
        doc,
        upsert=True,
    )
    return now


async def get_cache_meta(topic_slug: str, grade: int) -> Optional[dict]:
    """Return metadata only (no config payload). Used by /cache-status."""
    collection = await _get_collection()

    doc = await collection.find_one(
        {"topic_slug": topic_slug, "grade": grade},
        {"_id": 0, "config": 0},
    )
    if not doc:
        return None

    generated_at = doc.get("generated_at")
    return {
        "generated_at":   generated_at.isoformat() if generated_at else None,
        "generation_ms":  doc.get("generation_ms"),
        "prompt_version": doc.get("prompt_version"),
        "gemini_model":   doc.get("gemini_model"),
        "is_stale":       doc.get("prompt_version") != CURRENT_PROMPT_VERSION,
    }
