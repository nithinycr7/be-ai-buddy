"""
Capture metadata sidecar — carries the teacher's CANONICAL chapter/topic ids
from the audio-upload moment to summary generation, without touching the blob
filename or the transcription microservice.

The audio path drops canonical ids (only a title survives in the blob filename,
which the microservice parses). So at upload time we stash the canonical ids in a
`capture_meta` doc keyed by the class identity the summary flow already resolves
on — (tenant, class_no, section, subject) — and the summary flow reads them back
to scope NCERT grounding to the exact taught section.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def coerce_class_no(value: Any) -> int | None:
    """'9' / 'Class 9' / 9 → 9."""
    if value is None:
        return None
    m = re.search(r"\d+", str(value))
    return int(m.group(0)) if m else None


async def save_capture_meta(
    db,
    *,
    tenant: str,
    class_no: int | None,
    section: str,
    subject: str,
    chapter_key: str | None = None,
    topic_ids: list[str] | None = None,
    topics: list[str] | None = None,
) -> bool:
    """Upsert the canonical capture ids for a class. Returns True if stored.
    No-op when there's nothing canonical to carry."""
    if class_no is None or not subject:
        return False
    chapter_key = (chapter_key or "").strip() or None
    topic_ids = [t for t in (topic_ids or []) if t]
    if not chapter_key and not topic_ids:
        return False
    key = {"tenant": tenant, "class_no": class_no, "section": section or "A", "subject": subject}
    await db.capture_meta.update_one(
        key,
        {"$set": {**key, "chapter_key": chapter_key, "topic_ids": topic_ids,
                  "topics": [t for t in (topics or []) if t],
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    logger.info("[capture_meta] stored class=%s/%s %s chapter_key=%s topics=%d",
                class_no, section, subject, chapter_key, len(topic_ids))
    return True


async def get_capture_meta(
    db, *, tenant: str, class_no: int | None, section: str, subject: str, max_age_hours: int = 48,
) -> dict[str, Any] | None:
    """Most recent canonical capture for a class, if fresh enough (guards against
    matching a stale recording from a previous lesson)."""
    if class_no is None or not subject:
        return None
    doc = await db.capture_meta.find_one({
        "tenant": tenant, "class_no": class_no, "section": section or "A",
        "subject": {"$regex": f"^{re.escape(subject)}$", "$options": "i"},
    })
    if not doc:
        return None
    ts = doc.get("updated_at")
    if ts:
        try:
            when = datetime.fromisoformat(ts)
            if datetime.now(timezone.utc) - when > timedelta(hours=max_age_hours):
                return None
        except ValueError:
            pass
    return doc
