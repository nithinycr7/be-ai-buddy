"""
Eval-only (NOT committed): regenerate ONLY the faster_whisper summary + story
from the Whisper transcript already stored in daily_transcripts, reusing the
SAME topic + NCERT context the comparison already holds (constant across
providers). Then re-alias the comparison under the class-9 daily_id.
"""
import asyncio

TRANSCRIPT_ID = "evalschool_9_Science_1717200000"
DAILY_ID = "6a1dbc5cf7dff4850f0abfc0"


async def main():
    from app.db.mongo import get_db
    from app.services.summary_service import SummaryService
    from app.services.story_service import generate_story

    db = await get_db()
    svc = SummaryService(db.client)

    # Whisper transcript already stored in the collection
    tdoc = await db.daily_transcripts.find_one({"_id": TRANSCRIPT_ID})
    fw = (tdoc.get("transcripts") or {}).get("faster_whisper") or {}
    fw_text = (fw.get("transcript_text") or "").strip()
    if not fw_text:
        print("No faster_whisper transcript stored — nothing to do.")
        return
    print(f"Using stored Whisper transcript ({len(fw_text)} chars): {fw_text[:120]}…\n")

    # Reuse the comparison's constant topic + NCERT context
    comp = await db.provider_comparisons.find_one({"_id": TRANSCRIPT_ID})
    topic = comp.get("topic") or comp.get("subject")
    ncert = comp.get("ncert_used") or ""
    subject = comp.get("subject", "Science")
    grade = comp.get("class_no", 9)
    print(f"topic='{topic}' | grade={grade} | ncert={len(ncert)} chars\n")

    # Generate summary + story from the Whisper transcript
    print("⏳ generating Whisper summary + story…")
    summary = await svc._generate_llm_summary(fw_text, ncert)
    story, gen_ms = await generate_story(
        topic=topic, subject=subject, grade=grade,
        transcript=fw_text, ncert_content=ncert, personality="curious",
    )

    fw_meta = fw.get("metrics") or {}
    comp["providers"]["faster_whisper"] = {
        "summary": summary,
        "story": story,
        "transcription": {
            "latency_s": fw_meta.get("latency_s"),
            "estimated_cost_usd": fw_meta.get("estimated_cost_usd"),
            "language_detected": fw.get("language_detected"),
        },
        "error": None,
    }

    # Persist under the transcript_id doc AND the daily_id alias the FE reads
    await db.provider_comparisons.replace_one({"_id": TRANSCRIPT_ID}, comp, upsert=True)
    alias = dict(comp); alias["_id"] = DAILY_ID; alias["daily_id"] = DAILY_ID
    await db.provider_comparisons.replace_one({"_id": DAILY_ID}, alias, upsert=True)

    panels = (story or {}).get("panels") or []
    print(f"\n✅ whisper regenerated: summary={len(summary)} chars | story_panels={len(panels)} | {gen_ms}ms")
    print(f"   stored under _id={TRANSCRIPT_ID} and aliased to daily_id={DAILY_ID}")


if __name__ == "__main__":
    asyncio.run(main())
