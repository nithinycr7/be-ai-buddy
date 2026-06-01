"""
Provider comparison (internal/demo eval).

For one class, generate a summary AND a story from EACH transcription provider
(faster_whisper / sarvam / gemini) so we can judge which engine yields the best
student-facing content.

Key design (per approved plan):
- Topic + NCERT context are identified ONCE (from the primary transcript) and held
  CONSTANT across all providers — so the comparison isolates transcription quality.
- Reuses the existing generators unchanged: SummaryService._identify_topic /
  _fetch_ncert_context / _generate_llm_summary and story_service.generate_story.
- Results are stored in a NEW, isolated `provider_comparisons` collection. No
  production summary/story path is touched.

This is eval-only and removable.
"""
from __future__ import annotations
import re
import asyncio
import logging
from datetime import datetime

from bson import ObjectId

from app.db.mongo import get_db
from app.services.summary_service import SummaryService
from app.services.story_service import generate_story

logger = logging.getLogger(__name__)

PROVIDERS = ["faster_whisper", "sarvam", "gemini"]


def _sync_summary(svc, text, ctx) -> str:
    """Run the (blocking) summary coroutine in a worker thread via a fresh loop."""
    return asyncio.run(svc._generate_llm_summary(text, ctx))


def _grade_from(class_id, fallback) -> int:
    """Best-effort integer grade from a classId like '9', '9A', '09-B'."""
    if isinstance(class_id, (int, float)):
        return int(class_id)
    m = re.search(r"\d+", str(class_id or ""))
    if m:
        return int(m.group())
    return int(fallback or 7)


async def _resolve_trigger(db, transcripts_db, *, transcript_id, daily_id):
    """
    Return (trigger_doc, daily_id|None). Prefer an explicit transcript_id; otherwise
    resolve from a classes_daily doc by subject + date (+ class number), best-effort.
    """
    if transcript_id:
        doc = await transcripts_db.daily_transcripts.find_one({"_id": transcript_id})
        if not doc:
            raise ValueError(f"daily_transcripts not found for transcript_id={transcript_id}")
        return doc, daily_id

    if not daily_id:
        raise ValueError("Provide transcript_id or daily_id")
    if not ObjectId.is_valid(daily_id):
        raise ValueError("Invalid daily_id")
    daily = await db.classes_daily.find_one({"_id": ObjectId(daily_id)})
    if not daily:
        raise ValueError(f"classes_daily not found for daily_id={daily_id}")

    subject = daily.get("subject")
    class_no = daily.get("class_no")
    date_str = daily.get("date")  # 'YYYY-MM-DD'
    # Match transcripts on that calendar day for the same subject + class number.
    start = end = None
    if date_str:
        day = datetime.fromisoformat(date_str)
        start = int(day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        end = int(day.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())
    query = {"subject": subject}
    if start is not None:
        query["timestamp"] = {"$gte": start, "$lte": end}
    cursor = transcripts_db.daily_transcripts.find(query).sort("timestamp", -1)
    candidates = await cursor.to_list(length=50)
    if class_no is not None:
        candidates = [c for c in candidates if re.search(rf"\b{class_no}\b", str(c.get("classId", "")))] or candidates
    if not candidates:
        raise ValueError(f"No daily_transcripts match daily_id={daily_id} (subject={subject}, date={date_str})")
    return candidates[0], daily_id


def _provider_transcription_meta(related_docs, provider):
    """Aggregate the provider's transcription metrics across same-day docs."""
    cost = 0.0
    latency = 0.0
    lang = None
    any_present = False
    for d in related_docs:
        p = (d.get("transcripts") or {}).get(provider)
        if not p:
            continue
        any_present = True
        m = p.get("metrics") or {}
        cost += (m.get("estimated_cost_usd") or 0) or 0
        latency = max(latency, m.get("latency_s") or 0)
        lang = lang or p.get("language_detected")
    if not any_present:
        return None
    return {
        "latency_s": round(latency, 2),
        "estimated_cost_usd": round(cost, 6),
        "language_detected": lang,
    }


def _provider_text(related_docs, provider) -> str:
    parts = []
    for d in related_docs:
        p = (d.get("transcripts") or {}).get(provider) or {}
        t = (p.get("transcript_text") or "").strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts).strip()


async def generate_comparison(*, transcript_id=None, daily_id=None, grade=None, force=False) -> dict:
    db = await get_db()
    client = db.client                       # AsyncIOMotorClient behind the db
    svc = SummaryService(client)
    tdb = svc.transcripts_db                  # mymedha_dev

    doc_key = daily_id or transcript_id
    if not force and doc_key:
        cached = await db.provider_comparisons.find_one({"_id": doc_key})
        if cached:
            return cached

    trigger, daily_id = await _resolve_trigger(db, tdb, transcript_id=transcript_id, daily_id=daily_id)
    transcript_id = trigger["_id"]

    school_id = trigger.get("schoolId")
    class_id = trigger.get("classId")
    subject = trigger.get("subject")
    timestamp = trigger.get("timestamp")
    dt = datetime.fromtimestamp(timestamp) if timestamp else datetime.utcnow()
    grade_int = _grade_from(class_id, grade)

    # Aggregate same-day related transcripts (mirrors summary_service logic).
    start = int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    end = int(dt.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())
    related = await tdb.daily_transcripts.find({
        "schoolId": school_id, "classId": class_id, "subject": subject,
        "timestamp": {"$gte": start, "$lte": end},
    }).to_list(length=None)
    if not related:
        related = [trigger]

    # ── Topic + NCERT identified ONCE (constant across providers) ──
    primary_text = "\n\n".join([d.get("transcript_text", "") for d in related]).strip()
    topic_info = await svc._identify_topic(primary_text, class_id, subject)
    chapter_name = topic_info.get("chapter")
    topic_name = topic_info.get("topic")
    ncert_context = ""
    if chapter_name and topic_name:
        ncert_context = await svc._fetch_ncert_context(class_id, subject, chapter_name, topic_name)

    # ── Per-provider summary + story, run concurrently (failure-isolated) ──
    # generate_story is async; the summary LLM call is blocking, so we offload it
    # to a thread — this lets the three providers' work genuinely overlap.
    async def _run_provider(provider):
        entry = {"summary": None, "story": None,
                 "transcription": _provider_transcription_meta(related, provider),
                 "error": None}
        try:
            text = _provider_text(related, provider)
            if not text:
                entry["error"] = "No transcript text for this provider"
                return provider, entry
            summary, (story, _gen_ms) = await asyncio.gather(
                asyncio.to_thread(_sync_summary, svc, text, ncert_context),
                generate_story(
                    topic=topic_name or subject,
                    subject=subject,
                    grade=grade_int,
                    transcript=text,
                    ncert_content=ncert_context,
                    personality="curious",
                ),
            )
            entry["summary"] = summary
            entry["story"] = story
        except Exception as e:
            logger.error(f"[COMPARE] provider={provider} failed: {e}", exc_info=True)
            entry["error"] = repr(e)
        return provider, entry

    pairs = await asyncio.gather(*[_run_provider(p) for p in PROVIDERS])
    providers_out = {p: entry for p, entry in pairs}

    result = {
        "_id": doc_key or transcript_id,
        "daily_id": daily_id,
        "transcript_id": transcript_id,
        "class_no": grade_int,
        "subject": subject,
        "chapter": chapter_name,
        "topic": topic_name,
        "ncert_used": ncert_context,
        "providers": providers_out,
        "generated_at": datetime.utcnow().isoformat(),
    }
    await db.provider_comparisons.replace_one({"_id": result["_id"]}, result, upsert=True)
    logger.info(f"[COMPARE] saved comparison _id={result['_id']} topic='{topic_name}'")
    return result


async def get_comparison(*, transcript_id=None, daily_id=None) -> dict | None:
    db = await get_db()
    key = daily_id or transcript_id
    if not key:
        return None
    doc = await db.provider_comparisons.find_one({"_id": key})
    if doc:
        return doc
    # fall back to matching either field
    return await db.provider_comparisons.find_one(
        {"$or": [{"daily_id": daily_id}, {"transcript_id": transcript_id}]}
    )
