"""
Eval-only (NOT committed): regenerate the Class 9 'Internal Energy' student
content from the Google/Gemini STT transcript, using gemini-2.5-flash.
- summary_blocks (grounded in the Gemini transcript)  -> classes_daily
- daily quiz (from the seeded Gemini transcript)       -> quizzes
Runs in-process so it uses the freshly-edited Gemini code paths.
"""
import json
import asyncio
from bson import ObjectId

DAILY_ID = "6a1dbc5cf7dff4850f0abfc0"
TRANSCRIPT_ID = "evalschool_9_Science_1717200000"
TENANT = "demo-school"


async def main():
    from app.db.mongo import get_db
    from app.core.config import settings
    from app.services.ai import get_chat_client
    from app.routers.classes import SUMMARY_PROMPT, _validate_blocks
    from app.services.auto_quiz_generator import AutoQuizGenerator

    db = await get_db()
    print("chat model:", settings.GEMINI_CHAT_MODEL, "| story model:", settings.GEMINI_STORY_MODEL)

    # Gemini (Google STT) transcript
    td = await db.daily_transcripts.find_one({"_id": TRANSCRIPT_ID})
    gem_text = (td.get("transcripts") or {}).get("gemini", {}).get("transcript_text", "")
    print(f"Gemini transcript: {len(gem_text)} chars")

    # 1. summary_blocks grounded in the transcript, via Gemini
    client = get_chat_client()
    resp = client.chat.completions.create(
        model=settings.GEMINI_CHAT_MODEL,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT.format(class_no=9)},
            {"role": "user", "content": f"Class 9 Science — Internal Energy\n\nClassroom transcript:\n{gem_text}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    raw = resp.choices[0].message.content
    blocks = _validate_blocks(json.loads(raw))
    await db.classes_daily.update_one({"_id": ObjectId(DAILY_ID)}, {"$set": {"summary_blocks": blocks}})
    print(f"✓ summary_blocks regenerated via Gemini: {len(blocks)} blocks ({[b.get('type') for b in blocks]})")

    # 2. quiz from the Gemini transcript, via Gemini (force regenerate)
    gen = AutoQuizGenerator(db)
    quiz = await gen.generate_quiz_for_daily_class(daily_id=DAILY_ID, tenant=TENANT, force_regenerate=True)
    qs = (quiz or {}).get("questions") or []
    print(f"✓ quiz regenerated via Gemini: {len(qs)} questions | topic={quiz.get('topic') if quiz else None}")


if __name__ == "__main__":
    asyncio.run(main())
