"""
Transcript-grounded summary-blocks generation → classes_daily.summary_blocks.

This reuses the EXACT approved format from the `test-summary` endpoint (same
SUMMARY_PROMPT + _validate_blocks, lazily imported from the router so there is a
single source of truth) — but now grounds the summary in the teacher's lecture
transcript + the ingested NCERT chapter text, and stamps the structured blocks
straight into the `classes_daily` document the frontend reads.

Used by:
  • POST /api/classes/daily/{daily_id}/summary-from-transcript  (manual / demo)
  • the summary worker (audio → transcript → blocks)
  • app/scripts/gen_summary_from_transcript.py                  (CLI / demo)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def _prompt_and_validator():
    """Lazy import the approved prompt + validator from the router (avoids a
    circular import and keeps ONE definition of the approved format)."""
    from app.routers.classes import SUMMARY_PROMPT, _validate_blocks
    return SUMMARY_PROMPT, _validate_blocks


# Provider preference when the canonical top-level transcript_text is empty.
_PROVIDER_ORDER = ("gemini", "sarvam", "faster_whisper")


def make_daily_transcript_id(school_id: str, class_id: str, subject: str, timestamp: int) -> str:
    """The canonical daily_transcripts `_id`, identical to the transcription worker
    (pipeline-transcribe/worker.py): f"{schoolId}_{classId}_{subject}_{timestamp}".
    Use this for manual inserts so manual + worker docs are byte-for-byte consistent.
    """
    return f"{school_id}_{class_id}_{subject}_{timestamp}"


async def insert_daily_transcript(
    db_client, *, school_id: str, class_id: str, subject: str,
    transcript_text: str, timestamp: int | None = None, topic: str | None = None,
    chapter: str | None = None,
) -> dict:
    """Create a worker-shaped daily_transcripts doc with the CORRECT string `_id`.
    `db_client` is the Motor client (daily_transcripts live in the mymedha_dev DB)."""
    import time
    from datetime import datetime, timezone
    ts = int(timestamp) if timestamp else int(time.time())
    doc_id = make_daily_transcript_id(school_id, class_id, subject, ts)
    doc = {
        "_id": doc_id,
        "schoolId": school_id, "classId": class_id, "subject": subject,
        "timestamp": ts,
        "transcript_text": transcript_text,           # canonical top-level field
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "source": "manual",
    }
    if topic:
        doc["topic"] = topic
    if chapter:
        doc["chapter"] = chapter
    await db_client["mymedha_dev"].daily_transcripts.replace_one({"_id": doc_id}, doc, upsert=True)
    return {"transcript_id": doc_id, "timestamp": ts}


def best_transcript_text(doc: dict | None) -> str:
    """Best available transcript from a daily_transcripts doc:
    top-level `transcript_text` → else the best provider in `transcripts`
    (preferred order gemini → sarvam → faster_whisper → any other), preferring
    providers with `success: true` before falling back to any non-empty text."""
    if not doc:
        return ""
    txt = (doc.get("transcript_text") or "").strip()
    if txt:
        return txt

    providers = doc.get("transcripts") or {}
    names = list(_PROVIDER_ORDER) + [n for n in providers if n not in _PROVIDER_ORDER]
    # pass 1: success == true + non-empty;  pass 2: any non-empty text
    for require_success in (True, False):
        for name in names:
            p = providers.get(name) or {}
            if not isinstance(p, dict):
                continue
            t = (p.get("transcript_text") or "").strip()
            if t and (p.get("success") if require_success else True):
                return t
    return ""


async def generate_summary_blocks(
    *, class_no: int, subject: str, topic: str, transcript: str = "", ncert_content: str = "",
) -> list[dict[str, Any]]:
    """Generate structured summary blocks (approved format), grounded in the
    transcript + NCERT when available. Falls back to topic-only when not."""
    from app.services.ai import get_chat_client

    SUMMARY_PROMPT, _validate_blocks = _prompt_and_validator()
    client = get_chat_client()

    parts = [f"Class {class_no} {subject} — {topic}"]
    if transcript:
        parts.append(
            "\nTeacher's classroom transcript (PRIMARY source — keep their phrasing, "
            f"analogies and examples):\n{transcript[:6000]}"
        )
    if ncert_content:
        parts.append(
            "\nNCERT textbook reference (use for precise facts, definitions, formulas):\n"
            f"{ncert_content[:4000]}"
        )
    user_message = "\n".join(parts)

    try:
        resp = client.chat.completions.create(
            model=settings.GEMINI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT.format(class_no=class_no)},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        raw = resp.choices[0].message.content
        return _validate_blocks(json.loads(raw))
    except Exception as e:
        logger.error(f"[SUMMARY_BLOCKS] generation/validation failed: {e}")
        return [{"type": "concept", "title": topic, "content": "Summary not available — please try again."}]


async def resolve_ncert_content(db, class_no: int, subject: str, chapter_key: str | None = None) -> tuple[str, str | None]:
    """Best NCERT grounding for a class+subject: prefer the ingested chapter text,
    fall back to the curriculum_chapters concept snippet. Returns (content, chapter_key)."""
    if not chapter_key:
        ch = await db.curriculum_chapters.find_one(
            {"class": class_no, "subject": {"$regex": f"^{subject}$", "$options": "i"}},
            {"chapter_key": 1},
        )
        chapter_key = ch.get("chapter_key") if ch else None

    content = ""
    if chapter_key:
        pages = await db.ncert_chapter_text.find(
            {"chapter_key": chapter_key}, {"text": 1, "page": 1, "_id": 0}
        ).sort("page", 1).to_list(length=None)
        content = "\n".join(p.get("text", "") for p in pages)[:6000]

    if not content:
        ch = await db.curriculum_chapters.find_one(
            {"class": class_no, "subject": {"$regex": f"^{subject}$", "$options": "i"}}
        )
        if ch:
            concepts = "\n".join(
                f"- {c.get('name','')}: {c.get('explanation','')}" for c in ch.get("concepts", [])[:6]
            )
            content = (
                f"Chapter: {ch.get('chapter_title','')}\n"
                f"Summary: {ch.get('chapter_summary','')}\nConcepts:\n{concepts}"
            )
    return content, chapter_key


async def ensure_daily(
    db, *, daily_id: str | None = None, tenant: str = "demo-school",
    class_no: int | None = None, section: str = "A", subject: str | None = None,
    date: str | None = None, topics: list[str] | None = None, transcript_id: str | None = None,
) -> dict[str, Any]:
    """The single, shared way to get-or-create a classes_daily record (used by the
    API and the worker). Creates it if absent (carrying topics + transcript_id);
    if it exists, back-fills missing topics / transcript_id. Returns the doc.

    Matched by (class_no, section, subject, date) — NOT tenant — so the worker
    (which only knows class/subject/date) and the teacher-created doc resolve to
    the same record instead of duplicating.
    """
    from bson import ObjectId
    from datetime import datetime, timezone

    clean_topics = [t for t in (topics or []) if t]

    if daily_id:
        if not ObjectId.is_valid(daily_id):
            raise ValueError("Invalid daily_id")
        daily = await db.classes_daily.find_one({"_id": ObjectId(daily_id)})
        if not daily:
            raise ValueError(f"classes_daily {daily_id} not found")
    else:
        if class_no is None or not subject:
            raise ValueError("class_no + subject (+ date) are required to create a daily record")
        d = date or datetime.now(timezone.utc).date().isoformat()
        match = {"class_no": class_no, "section": section, "subject": subject, "date": d}
        daily = await db.classes_daily.find_one(match)
        if not daily:
            doc = {
                **match, "tenant": tenant, "topics": clean_topics, "summary_blocks": [],
                "transcript_id": transcript_id, "source": "transcript_flow",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            res = await db.classes_daily.insert_one(doc)
            daily = {**doc, "_id": res.inserted_id}
            logger.info(f"[ensure_daily] created classes_daily {match}")

    # back-fill only what's missing (never clobber existing topics/transcript)
    updates = {}
    if clean_topics and not [t for t in (daily.get("topics") or []) if t]:
        updates["topics"] = clean_topics
    if transcript_id and not daily.get("transcript_id"):
        updates["transcript_id"] = transcript_id
    if updates:
        await db.classes_daily.update_one({"_id": daily["_id"]}, {"$set": updates})
        daily.update(updates)
    return daily


async def summarize_daily_from_transcript(
    db, *, daily_id: str | None = None, tenant: str = "demo-school",
    class_no: int | None = None, section: str = "A", subject: str | None = None,
    date: str | None = None, topics: list[str] | None = None,
    transcript_text: str | None = None, transcript_id: str | None = None,
    chapter_key: str | None = None, force: bool = False,
) -> dict[str, Any]:
    """Unified flow for both the API and the worker:
      1. ensure the classes_daily record exists (create if absent, carrying transcript_id)
      2. persist the transcript (so it grounds the Story too)
      3. if summary_blocks are missing (or force=True): generate the approved blocks
         from transcript + NCERT and stamp them in.
    """
    daily = await ensure_daily(
        db, daily_id=daily_id, tenant=tenant, class_no=class_no, section=section,
        subject=subject, date=date, topics=topics, transcript_id=transcript_id,
    )
    daily_id = str(daily["_id"])
    subject = daily.get("subject", subject or "Science")
    class_no = daily.get("class_no", class_no or 9)
    topic = ", ".join([t for t in (daily.get("topics") or []) if t]) or subject

    # persist inline transcript (keyed by daily_id) — grounds the Story as well
    if transcript_text:
        from datetime import datetime, timezone
        await db.transcripts.replace_one(
            {"daily_id": daily_id},
            {"daily_id": daily_id, "text": transcript_text, "source": "manual",
             "created_at": datetime.now(timezone.utc).isoformat()},
            upsert=True,
        )

    # idempotent: don't regenerate an existing summary unless explicitly forced
    if daily.get("summary_blocks") and not force:
        return {
            "daily_id": daily_id, "topic": topic, "skipped": True,
            "reason": "summary_blocks already present (pass force=true to regenerate)",
            "blocks_count": len(daily["summary_blocks"]),
        }

    # resolve transcript: inline → daily_transcripts[id] (with provider fallback) → transcripts[daily_id]
    transcript = transcript_text or ""
    if not transcript and transcript_id:
        td = await db.daily_transcripts.find_one({"_id": transcript_id})
        transcript = best_transcript_text(td)
    if not transcript:
        td = await db.transcripts.find_one({"daily_id": daily_id})
        transcript = (td or {}).get("text", "") if td else ""

    ncert_content, chapter_key = await resolve_ncert_content(db, class_no, subject, chapter_key)
    blocks = await generate_summary_blocks(
        class_no=class_no, subject=subject, topic=topic,
        transcript=transcript, ncert_content=ncert_content,
    )
    await db.classes_daily.update_one({"_id": daily["_id"]}, {"$set": {"summary_blocks": blocks}})
    logger.info(
        f"[SUMMARY_BLOCKS] stamped {len(blocks)} blocks into daily_id={daily_id} "
        f"topic='{topic}' transcript_chars={len(transcript)} chapter_key={chapter_key}"
    )
    return {
        "daily_id": daily_id, "topic": topic, "skipped": False,
        "blocks_count": len(blocks), "block_types": [b.get("type") for b in blocks],
        "used_transcript": bool(transcript), "transcript_chars": len(transcript),
        "chapter_key": chapter_key,
    }
