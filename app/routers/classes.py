from __future__ import annotations
# app/routers/classes.py
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from datetime import date as dt_date, datetime, timezone
from pydantic import BaseModel
from bson import ObjectId
from app.core.config import settings
from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from ..models.schemas import DailyClass, Summary
from ..services.ai import summarize as ai_summarize, get_client, get_chat_client
from ..services.auto_quiz_generator import AutoQuizGenerator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/classes", tags=["classes"], dependencies=[Depends(api_key_guard)])

# ---------- helpers ----------
def _today_iso() -> str:
    return dt_date.today().isoformat()


async def _eager_generate_quiz(db, daily_id: str, tenant: str) -> None:
    """Fire-and-forget quiz generation, called after summary save.
    Auto_generator already handles cache check, so re-runs are no-ops."""
    try:
        generator = AutoQuizGenerator(db)
        quiz = await generator.generate_quiz_for_daily_class(
            daily_id=daily_id, tenant=tenant, force_regenerate=False
        )
        if quiz:
            logger.info(f"[QUIZ_EAGER] Quiz ready for daily_id={daily_id}")
        else:
            logger.warning(f"[QUIZ_EAGER] Generation returned no quiz for daily_id={daily_id}")
    except Exception as e:
        logger.error(f"[QUIZ_EAGER] Background generation failed for daily_id={daily_id}: {e}")

async def _get_or_create_daily(db, *, tenant: str, class_no: int, section: str, subject: str, date_str: str | None = None) -> str:
    d = date_str or _today_iso()
    existing = await db.classes_daily.find_one({
        "tenant": tenant, "date": d, "class_no": class_no, "section": section, "subject": subject
    })
    if existing:
        return str(existing["_id"])
    res = await db.classes_daily.insert_one({
        "tenant": tenant,
        "date": d,
        "class_no": class_no,
        "section": section,
        "subject": subject,
        "topics": [],
        "summary": None
    })
    return str(res.inserted_id)

# ---------- existing endpoints (fixed) ----------
@router.post("/daily", response_model=DailyClass, status_code=201)
async def create_daily(payload: DailyClass, tenant: str = Depends(get_tenant)):
    db = await get_db()
    # Ensure tenant from header overrides or is set if missing in payload (though payload has it mandatory now)
    # Actually, DailyClass has tenant mandatory. The client should send it in body OR we override it.
    # Better pattern: The API client sends X-Tenant-ID. We set it on the model.
    data = payload.model_dump(by_alias=True, exclude_none=True)
    data['tenant'] = tenant
    res = await db.classes_daily.insert_one(data)
    payload.id = str(res.inserted_id)
    payload.tenant = tenant
    return payload


@router.post("/daily/{daily_id}/summarize", response_model=Summary)
async def summarize_daily(daily_id: str):
    db = await get_db()
    if not ObjectId.is_valid(daily_id) or not await db.classes_daily.find_one({"_id": ObjectId(daily_id)}):
        raise HTTPException(status_code=404, detail="Daily class not found")

    t = await db.transcripts.find_one({"daily_id": daily_id})
    base = t["text"] if t else ""
    d = await db.classes_daily.find_one({"_id": ObjectId(daily_id)})
    if d and d.get("summary"):
        base = d["summary"] + "\n" + base
    text = await ai_summarize(base) if base else ""
    res = await db.summaries.insert_one({"daily_id": daily_id, "text": text})
    return Summary(id=str(res.inserted_id), daily_id=daily_id, text=text)


@router.get("/daily", response_model=list[DailyClass])
async def list_daily_classes(
    class_no: int,
    section: str,
    date: str | None = None,
    student_id: str | None = None,
    demo: bool = False,
    tenant: str = Depends(get_tenant)
):
    db = await get_db()
    query = {"tenant": tenant, "class_no": class_no, "section": section}
    if demo:
        # Demo mode: return all classes irrespective of date (for MVP demos)
        pass
    elif date:
        query["date"] = date
    else:
        # Default: only return today's classes
        query["date"] = _today_iso()

    cursor = db.classes_daily.find(query).sort("date", -1).limit(50)
    results = []
    
    # Process classes
    classes = await cursor.to_list(length=50)
    
    # If student_id provided, fetch progress
    progress_map = {}
    if student_id and classes:
        daily_ids = [str(c["_id"]) for c in classes]
        p_cursor = db.student_daily_progress.find({
            "student_id": student_id,
            "daily_id": {"$in": daily_ids}
        })
        async for p in p_cursor:
            progress_map[p["daily_id"]] = p
            
    for doc in classes:
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        
        # Instantiate DailyClass
        d_obj = DailyClass(**doc)
        
        # Inject progress
        if d_obj.id in progress_map:
            p = progress_map[d_obj.id]
            d_obj.completed = p.get("is_complete", False)
            d_obj.progress = p.get("total_score", 0.0)
            
        results.append(d_obj)
        
    return results


# ---------- TEST: Generate structured JSON summary from curriculum data ----------
SUMMARY_PROMPT = """You are creating a revision summary for a Class {class_no} student who attended this class today.
You have two sources. Blend them into ONE confident voice per concept.
Never show them as separate competing paragraphs.

BLENDING RULES:
- Use teacher analogies and examples — keep their phrasing
- Use NCERT for precise facts, formulas, definitions
- Write ONE explanation per concept that honours both sources naturally
- If teacher simplified something NCERT states precisely: keep teacher framing, add NCERT precision
- Never write "teacher said X, NCERT says Y" — student reads ONE clear thing

CLASS LEVEL GUIDE:
- Class 3-5: Simple everyday words. Max 3 key terms. No formulas.
- Class 6-7: Simple scientific vocabulary. Max 5 key terms. Basic formulas.
- Class 8-9: Standard terminology. Concise definitions. Include formulas.

REQUIRED BLOCK ORDER:
1. concept blocks (2-4) — each must have:
   {{ "type": "concept", "title": "...", "content": "...", "icon": "<1 emoji that represents this concept visually>",
      "sources": ["teacher", "ncert"] }}
   sources options: ["teacher","ncert"] if both used | ["ncert"] if teacher didn't cover it | ["teacher"] if not in NCERT

2. analogy block — REQUIRED. Create a vivid real-world comparison that makes the concept memorable.
   If the teacher used one, keep their exact words. Otherwise invent a strong one.
   {{ "type": "analogy", "content": "..." }}

3. formula block — ONLY for Math/Science with an equation:
   {{ "type": "formula", "label": "The equation", "expression": "...", "note": "..." }}

4. terms block — key vocabulary, always visible with definition:
   {{ "type": "terms", "items": [{{ "term": "...", "meaning": "..." }}] }}

OPTIONAL additional types (use only if they genuinely fit):
- "fact":     {{"type":"fact","items":["..."]}}
- "timeline": {{"type":"timeline","items":[{{"date":"1857","event":"..."}}]}}
- "rule":     {{"type":"rule","title":"...","content":"...","example":"..."}}
- "steps":    {{"type":"steps","title":"...","steps":["...","..."]}}

Return ONLY valid JSON. 4-7 blocks total. NEVER include a checkpoint block. NEVER show NCERT quotes separately."""


VALID_BLOCK_TYPES = {"concept", "terms", "steps", "analogy", "formula", "fact", "timeline", "rule"}


def _validate_blocks(data) -> list[dict]:
    """Validate and sanitize LLM JSON output. Returns cleaned blocks.
    Accepts either a top-level list (Gemini often returns this), a {"blocks": [...]}
    object (Azure/OpenAI), or any dict that nests the list under another key."""
    if isinstance(data, list):
        blocks = data
    elif isinstance(data, dict):
        blocks = data.get("blocks")
        if not isinstance(blocks, list):
            blocks = next((v for v in data.values() if isinstance(v, list)), [])
    else:
        blocks = []
    if not isinstance(blocks, list) or len(blocks) == 0:
        raise ValueError("No blocks in response")

    cleaned = []
    for b in blocks[:10]:  # Cap at 10 blocks (5-8 expected, room for teacher_moment + concept pairs)
        if not isinstance(b, dict) or "type" not in b:
            continue
        if b["type"] not in VALID_BLOCK_TYPES:
            continue
        cleaned.append(b)

    # Must have at least concept
    types = {b["type"] for b in cleaned}
    if "concept" not in types:
        raise ValueError("Missing required 'concept' block")

    return cleaned


@router.post("/daily/test-summary")
async def test_generate_summary(
    subject: str = Query(None, description="e.g. Science, Maths, English"),
    chapter_number: int = Query(1, description="Chapter number (only used when daily_id is not provided)"),
    class_no: int = Query(7, description="Class number"),
    section: str = Query("A"),
    daily_id: str | None = Query(None, description="If provided, regenerate summary for this doc using its own topic"),
    tenant: str = Depends(get_tenant)
):
    """
    Regenerate structured summary blocks for a classes_daily document.

    When daily_id is given: reads topic/subject/class directly from the document
    and generates from that — no curriculum chapter lookup needed.

    When daily_id is not given: looks up a curriculum chapter by subject +
    chapter_number and creates a new row for today.
    """
    import json as json_mod

    db = await get_db()
    client = get_chat_client()   # summary blocks → Gemini (gemini-2.5-flash)
    prompt_tmpl = SUMMARY_PROMPT

    # ── PATH A: daily_id provided — use the doc's own data ──────────────────
    if daily_id:
        if not ObjectId.is_valid(daily_id):
            raise HTTPException(400, "Invalid daily_id")
        doc = await db.classes_daily.find_one({"_id": ObjectId(daily_id)})
        if not doc:
            raise HTTPException(404, f"classes_daily {daily_id} not found")

        topic_list = [t for t in (doc.get("topics") or []) if t]
        if not topic_list:
            raise HTTPException(400, "Document has no topics — set topics before regenerating")

        doc_subject  = doc.get("subject", "Science")
        doc_class_no = doc.get("class_no", 7)
        topic_str    = ", ".join(topic_list)

        resp = client.chat.completions.create(
            model=settings.GEMINI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": prompt_tmpl.format(class_no=doc_class_no)},
                {"role": "user",   "content": f"Class {doc_class_no} {doc_subject} — {topic_str}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )

        raw = resp.choices[0].message.content
        try:
            blocks = _validate_blocks(json_mod.loads(raw))
        except (json_mod.JSONDecodeError, ValueError) as e:
            logger.error(f"LLM JSON validation failed: {e}\nRaw: {raw[:500]}")
            blocks = [{"type": "concept", "title": topic_str, "content": "Summary not available — please try again."}]

        await db.classes_daily.update_one(
            {"_id": doc["_id"]},
            {"$set": {"summary_blocks": blocks}}  # topics stay unchanged
        )

        logger.info(f"Regenerated summary for daily_id={daily_id} topic='{topic_str}'")
        asyncio.create_task(_eager_generate_quiz(db, daily_id, tenant))
        return {
            "status": "ok",
            "daily_id": daily_id,
            "subject": doc_subject,
            "topic": topic_str,
            "date": doc.get("date"),
            "blocks_count": len(blocks),
            "block_types": [b["type"] for b in blocks]
        }

    # ── PATH B: no daily_id — look up curriculum chapter and upsert today ───
    if not subject:
        raise HTTPException(400, "subject is required when daily_id is not provided")

    SUBJECT_FALLBACKS = {
        "biology": ["Science"], "physics": ["Science"], "chemistry": ["Science"],
        "history": ["Social Science"], "geography": ["Social Science"], "civics": ["Social Science"],
        "math": ["Maths"], "mathematics": ["Maths"],
    }

    chapter = None
    for s in [subject] + SUBJECT_FALLBACKS.get(subject.lower(), []):
        chapter = await db.curriculum_chapters.find_one({
            "class": class_no,
            "subject": {"$regex": f"^{s}$", "$options": "i"},
            "chapter_number": chapter_number
        })
        if chapter:
            break

    if not chapter:
        raise HTTPException(404, f"No curriculum found for class {class_no}, {subject}, chapter {chapter_number}")

    concepts_text = "".join(f"\n- {c.get('name','')}: {c.get('explanation','')}" for c in chapter.get("concepts", []))
    textbook_content = (
        f"Chapter: {chapter.get('chapter_title','')}\n"
        f"Summary: {chapter.get('chapter_summary','')}\n"
        f"Key Concepts:{concepts_text}\n"
        f"Formulas/Rules: {', '.join(str(x) for x in chapter.get('key_formulas_or_rules', []))}\n"
        f"Real World Connections: {', '.join(str(x) for x in chapter.get('real_world_connections', []))}"
    )

    resp = client.chat.completions.create(
        model=settings.GEMINI_CHAT_MODEL,
        messages=[
            {"role": "system", "content": prompt_tmpl.format(class_no=class_no)},
            {"role": "user",   "content": f"Class {class_no} {subject} — {chapter.get('chapter_title','')}\n\n{textbook_content}"}
        ],
        response_format={"type": "json_object"},
        temperature=0.3
    )

    raw = resp.choices[0].message.content
    try:
        blocks = _validate_blocks(json_mod.loads(raw))
    except (json_mod.JSONDecodeError, ValueError) as e:
        logger.error(f"LLM JSON validation failed: {e}\nRaw: {raw[:500]}")
        blocks = [
            {"type": "concept", "title": chapter.get("chapter_title", subject), "content": chapter.get("chapter_summary", "")},
            {"type": "terms",   "items": [{"term": c.get("name",""), "meaning": c.get("explanation","")[:80]} for c in chapter.get("concepts",[])[:5]]},
        ]

    topics = [c.get("name", "") for c in chapter.get("concepts", [])[:3]]
    target_date = _today_iso()
    result = await db.classes_daily.update_one(
        {"tenant": tenant, "class_no": class_no, "section": section,
         "subject": chapter.get("subject", subject), "date": target_date},
        {"$set": {"tenant": tenant, "class_no": class_no, "section": section,
                  "subject": chapter.get("subject", subject), "date": target_date,
                  "topics": topics, "summary_blocks": blocks}},
        upsert=True
    )
    result_id = str(result.upserted_id) if result.upserted_id else "updated"

    logger.info(f"Created summary for {subject} ch{chapter_number} -> {result_id}")
    if result.upserted_id:
        asyncio.create_task(_eager_generate_quiz(db, result_id, tenant))
    return {
        "status": "ok",
        "daily_id": result_id,
        "subject": chapter.get("subject", subject),
        "chapter": chapter.get("chapter_title", ""),
        "date": target_date,
        "blocks_count": len(blocks),
        "block_types": [b["type"] for b in blocks]
    }


@router.post("/daily/mindmap")
async def generate_daily_mindmap(
    daily_id: str = Query(..., description="classes_daily document id"),
    force: bool = Query(False, description="Regenerate even if a mind map is cached"),
    tenant: str = Depends(get_tenant),
):
    """
    Hierarchical mind-map tree for a class, built from its summary_blocks
    (concept titles + key terms). Lazy + cached: generated on first request and
    stamped onto the classes_daily doc as `mindmap`, so every existing class can
    get a map without regenerating its summary.

    Returns { "root": str, "branches": [ {label, note?, children?}, ... ] }.
    """
    from app.services.mindmap import generate_mindmap

    if not ObjectId.is_valid(daily_id):
        raise HTTPException(400, "Invalid daily_id")

    db = await get_db()
    doc = await db.classes_daily.find_one({"_id": ObjectId(daily_id)})
    if not doc:
        raise HTTPException(404, f"classes_daily {daily_id} not found")

    cached = doc.get("mindmap")
    if cached and not force:
        return cached

    blocks = doc.get("summary_blocks") or []
    topics = [t for t in (doc.get("topics") or []) if t]
    topic_str = ", ".join(topics) if topics else doc.get("subject", "Today's Topic")

    tree = await generate_mindmap(
        class_no=doc.get("class_no", 7),
        subject=doc.get("subject", "Science"),
        topic=topic_str,
        summary_blocks=blocks,
    )

    await db.classes_daily.update_one(
        {"_id": doc["_id"]}, {"$set": {"mindmap": tree}}
    )
    logger.info(f"Generated mind map for daily_id={daily_id} ({len(tree.get('branches', []))} branches)")
    return tree


# ---------- Transcript-grounded summary (manual / demo flow) ----------
# Drop a transcript in the DB, then generate the approved summary_blocks from it
# straight into classes_daily — the backup path when there's no audio to record.

class ManualTranscript(BaseModel):
    text: str


class SummarizeRequest(BaseModel):
    # Either point at an existing daily…
    daily_id:        str | None = None
    # …or provide these to create-if-missing (matched by class_no/section/subject/date):
    class_no:        int | None = None
    section:         str = "A"
    subject:         str | None = None
    date:            str | None = None          # ISO date; defaults to today
    topics:          list[str] | None = None
    # transcript source + options
    transcript_id:   str | None = None          # daily_transcripts _id (audio pipeline)
    transcript_text: str | None = None          # paste raw transcript directly
    chapter_key:     str | None = None          # optional NCERT chapter override
    force:           bool = False               # regenerate even if summary_blocks exist


@router.post("/daily/{daily_id}/transcript")
async def add_manual_transcript(
    daily_id: str, payload: ManualTranscript, tenant: str = Depends(get_tenant),
):
    """Manually stamp a transcript for a daily class (keyed by daily_id) — the same
    `transcripts` collection the story/summary read. Use for demos without audio."""
    db = await get_db()
    if not ObjectId.is_valid(daily_id):
        raise HTTPException(400, "Invalid daily_id")
    if not await db.classes_daily.find_one({"_id": ObjectId(daily_id)}):
        raise HTTPException(404, "Daily class not found")
    now = datetime.now(timezone.utc).isoformat()
    await db.transcripts.replace_one(
        {"daily_id": daily_id},
        {"daily_id": daily_id, "text": payload.text, "source": "manual", "tenant": tenant, "created_at": now},
        upsert=True,
    )
    return {"status": "ok", "daily_id": daily_id, "chars": len(payload.text)}


class DailyTranscriptDoc(BaseModel):
    school_id:       str = "evalschool"
    class_id:        str                       # "9" or "9A"
    subject:         str = "Science"
    transcript_text: str
    timestamp:       int | None = None         # epoch seconds; defaults to now
    topic:           str | None = None         # optional; skips LLM topic-identification
    chapter:         str | None = None


@router.post("/daily/transcript-doc")
async def create_daily_transcript_doc(req: DailyTranscriptDoc, tenant: str = Depends(get_tenant)):
    """Insert a daily_transcripts doc the CORRECT way — with the worker's composite
    string `_id` ({schoolId}_{classId}_{subject}_{timestamp}) — so manual docs are
    consistent with audio-pipeline docs. Returns the `transcript_id` to summarize with."""
    from app.db.mongo import get_client
    from app.services.summary_blocks import insert_daily_transcript
    if not (req.transcript_text or "").strip():
        raise HTTPException(400, "transcript_text is required")
    res = await insert_daily_transcript(
        get_client(), school_id=req.school_id, class_id=req.class_id, subject=req.subject,
        transcript_text=req.transcript_text, timestamp=req.timestamp,
        topic=req.topic, chapter=req.chapter,
    )
    return {"status": "ok", **res}


@router.post("/daily/summarize")
async def daily_summarize(
    req: SummarizeRequest = Body(default=SummarizeRequest()),
    tenant: str = Depends(get_tenant),
):
    """Unified summary entry. Two modes:

    • transcript_id ONLY  → drive everything from the daily_transcripts doc: derive
      class/section/subject/date, identify the topic, ensure classes_daily, summarize.
    • daily_id / explicit → ensure the classes_daily record (create if absent), then
      summarize from the inline text or the transcripts[daily_id] entry.

    Either way it skips if summary_blocks already exist (unless force=true) and stamps
    transcript_id onto the classes_daily doc."""
    db = await get_db()

    # ── Mode A: transcript-doc driven (just a daily_transcripts._id) ──────────
    if req.transcript_id and not req.daily_id and req.class_no is None:
        from app.services.summary_service import SummaryService
        from app.db.mongo import get_client as get_mongo_client
        try:
            result = await SummaryService(get_mongo_client()).generate_summary(req.transcript_id, force=req.force)
        except Exception as e:
            raise HTTPException(500, f"Summary generation failed: {e}")
        if not result:
            raise HTTPException(400, f"Could not summarize transcript_id={req.transcript_id} (not found / topic not identified)")
        if not result.get("skipped"):
            asyncio.create_task(_eager_generate_quiz(db, result["daily_id"], tenant))
        return {"status": "ok", **result}

    # ── Mode B: daily_id / explicit fields / inline text ──────────────────────
    from app.services.summary_blocks import summarize_daily_from_transcript
    try:
        result = await summarize_daily_from_transcript(
            db, daily_id=req.daily_id, tenant=tenant,
            class_no=req.class_no, section=req.section, subject=req.subject,
            date=req.date, topics=req.topics,
            transcript_text=req.transcript_text, transcript_id=req.transcript_id,
            chapter_key=req.chapter_key, force=req.force,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Summary generation failed: {e}")

    if not result.get("skipped"):
        asyncio.create_task(_eager_generate_quiz(db, result["daily_id"], tenant))
    return {"status": "ok", **result}


# ---------- Try It Yourself widget generation ----------
WIDGET_PROMPT = """You generate interactive "Try It Yourself" widgets for students. Return ONLY valid JSON.

Choose the BEST widget type for the subject and topic:

1. "slider_simulation" — for exploring formulas by changing values (Math, Physics)
   {{
     "widget_type": "slider_simulation",
     "title": "Explore Area of Circle",
     "instruction": "Drag the slider to change radius and watch area update!",
     "formula": "A = π × r²",
     "variables": [
       {{"name": "radius", "label": "Radius (r)", "min": 1, "max": 10, "default": 3, "unit": "cm", "emoji": "📏"}}
     ],
     "outputs": [
       {{"name": "area", "label": "Area", "expression": "Math.PI * radius * radius", "unit": "cm²", "emoji": "⭕", "decimals": 2}}
     ],
     "visual_type": "circle"
   }}

2. "parameter_simulation" — for exploring cause-effect with multiple variables (Physics, Chemistry)
   {{
     "widget_type": "parameter_simulation",
     "title": "Newton's Second Law",
     "instruction": "Change force and mass to observe acceleration.",
     "formula": "a = F ÷ m",
     "variables": [
       {{"name": "force", "label": "Force (F)", "min": 1, "max": 100, "default": 20, "unit": "N", "emoji": "💪"}},
       {{"name": "mass", "label": "Mass (m)", "min": 1, "max": 50, "default": 10, "unit": "kg", "emoji": "⚖️"}}
     ],
     "outputs": [
       {{"name": "acceleration", "label": "Acceleration", "expression": "force / mass", "unit": "m/s²", "emoji": "🚀", "decimals": 2}}
     ],
     "visual_type": "motion"
   }}

3. "drag_sequence" — for ordering steps/processes (Science, History, any sequential concept)
   {{
     "widget_type": "drag_sequence",
     "title": "Order the Photosynthesis Steps",
     "instruction": "Tap a step, then tap its correct position.",
     "items": [
       {{"id": "1", "label": "Sunlight hits leaf", "emoji": "☀️", "correct_position": 1}},
       {{"id": "2", "label": "Chlorophyll absorbs light", "emoji": "🌿", "correct_position": 2}},
       {{"id": "3", "label": "CO₂ + Water react", "emoji": "💧", "correct_position": 3}},
       {{"id": "4", "label": "Glucose + Oxygen produced", "emoji": "🍃", "correct_position": 4}}
     ]
   }}

4. "step_builder" — for solving problems step by step (Math, Grammar)
   {{
     "widget_type": "step_builder",
     "title": "Solve: 2x + 4 = 10",
     "instruction": "Choose the correct next step.",
     "steps": [
       {{"prompt": "Step 1: Subtract 4 from both sides", "options": ["2x = 6", "2x = 14", "x = 6"], "correct": 0, "explanation": "10 − 4 = 6"}},
       {{"prompt": "Step 2: Divide by 2", "options": ["x = 3", "x = 12", "x = 2"], "correct": 0, "explanation": "6 ÷ 2 = 3"}}
     ]
   }}

RULES:
- Use ONLY facts from the provided content
- For expressions: use JavaScript math (Math.PI, *, /, +, -)
- Variable names in expressions must match the "name" field exactly
- Keep it simple for Class {{class_no}} students
- For science processes: prefer drag_sequence
- For math/physics formulas: prefer slider_simulation or parameter_simulation
- For problem solving: prefer step_builder
- Return exactly ONE widget object"""


@router.post("/daily/generate-widget")
async def generate_tryit_widget(
    subject: str = Query(..., description="e.g. Science, Maths"),
    chapter_number: int = Query(1),
    class_no: int = Query(7),
    section: str = Query("A"),
    tenant: str = Depends(get_tenant)
):
    """Generate a Try It Yourself widget from curriculum data and stamp into classes_daily."""
    import json as json_mod

    db = await get_db()

    # 1. Fetch curriculum chapter
    chapter = await db.curriculum_chapters.find_one({
        "class": class_no,
        "subject": {"$regex": f"^{subject}$", "$options": "i"},
        "chapter_number": chapter_number
    })
    if not chapter:
        raise HTTPException(404, f"No curriculum found for class {class_no}, {subject}, chapter {chapter_number}")

    # 2. Build context
    concepts_text = "\n".join(
        f"- {c.get('name', '')}: {c.get('explanation', '')}"
        for c in chapter.get("concepts", [])
    )
    formulas = ", ".join(str(x) for x in chapter.get("key_formulas_or_rules", []))

    content = f"""Class {class_no} {subject} — {chapter.get('chapter_title', '')}
Concepts: {concepts_text}
Formulas: {formulas}"""

    # 3. Generate widget via LLM
    client = get_client()
    prompt = WIDGET_PROMPT.replace("{{class_no}}", str(class_no))

    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": content}
        ],
        response_format={"type": "json_object"},
        temperature=0.3
    )

    try:
        widget = json_mod.loads(resp.choices[0].message.content)
        if "widget_type" not in widget:
            raise ValueError("Missing widget_type")
    except (json_mod.JSONDecodeError, ValueError) as e:
        logger.error(f"Widget generation failed: {e}")
        # Fallback: drag_sequence from concepts
        concepts = chapter.get("concepts", [])[:4]
        widget = {
            "widget_type": "drag_sequence",
            "title": f"Order the Key Concepts: {chapter.get('chapter_title', '')}",
            "instruction": "Tap a concept, then tap its correct position.",
            "items": [
                {"id": str(i+1), "label": c.get("name", ""), "emoji": "📌", "correct_position": i+1}
                for i, c in enumerate(concepts)
            ]
        }

    # 4. Stamp into classes_daily
    today = _today_iso()
    await db.classes_daily.update_one(
        {"tenant": tenant, "class_no": class_no, "section": section, "subject": chapter.get("subject", subject), "date": today},
        {"$set": {"try_it_widget": widget}},
        upsert=False  # only update existing daily class
    )

    logger.info(f"Widget generated for {subject} ch{chapter_number}: {widget.get('widget_type')}")

    return {
        "status": "ok",
        "widget_type": widget.get("widget_type"),
        "title": widget.get("title"),
        "subject": chapter.get("subject", subject),
        "chapter": chapter.get("chapter_title", "")
    }


# ---------- Comic Story endpoints ----------

@router.get("/daily/{daily_id}/comic")
async def get_comic_story(
    daily_id: str,
    student_id: str | None = Query(None),
    tenant: str = Depends(get_tenant),
):
    """
    Fetch (or generate and cache) the animated comic story for a daily class.
    Results are stored in the comic_stories collection.
    """
    if not ObjectId.is_valid(daily_id):
        raise HTTPException(status_code=400, detail="Invalid daily_id")

    db = await get_db()

    cached = await db.comic_stories.find_one({"daily_id": daily_id})
    if cached:
        cached["_id"] = str(cached["_id"])
        return cached

    doc = await db.classes_daily.find_one({"_id": ObjectId(daily_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Daily class not found")

    topics = [t for t in (doc.get("topics") or []) if t]
    if not topics:
        raise HTTPException(status_code=400, detail="No topics set for this class — ask your teacher to configure today's lesson")

    topic_str = ", ".join(topics)
    subject = doc.get("subject", "Science")
    class_no = doc.get("class_no", 7)

    persona_theme = "adventure"
    if student_id:
        student_doc = (
            await db.students.find_one({"_id": student_id})
            or await db.students.find_one({"student_id": student_id})
        )
        if student_doc:
            persona = student_doc.get("story_persona") or {}
            if isinstance(persona, dict):
                persona_theme = persona.get("theme") or persona_theme

    from app.services.story_service import generate_comic_story
    story_data = await generate_comic_story(
        topic=topic_str,
        subject=subject,
        class_no=class_no,
        persona_theme=persona_theme,
    )

    story_doc = {
        "daily_id": daily_id,
        "tenant": tenant,
        "subject": subject,
        "class_no": class_no,
        "topic": topic_str,
        **story_data,
    }
    result = await db.comic_stories.insert_one(story_doc)
    story_doc["_id"] = str(result.inserted_id)

    logger.info(f"Generated comic story for daily_id={daily_id} topic='{topic_str}'")
    return story_doc


@router.post("/daily/{daily_id}/comic-progress")
async def update_comic_progress(
    daily_id: str,
    student_id: str = Body(...),
    panels_read: int = Body(...),
    completed: bool = Body(False),
    tenant: str = Depends(get_tenant),
):
    """Track a student's reading progress through the animated comic story."""
    if not ObjectId.is_valid(daily_id):
        raise HTTPException(status_code=400, detail="Invalid daily_id")

    db = await get_db()

    cached = await db.comic_stories.find_one({"daily_id": daily_id}, {"panels": 1, "completion_xp": 1})
    total_panels = len(cached.get("panels", [])) if cached else panels_read
    base_xp = (cached or {}).get("completion_xp", 50)

    await db.student_daily_progress.update_one(
        {"student_id": student_id, "daily_id": daily_id},
        {
            "$set": {
                "comic_panels_read": panels_read,
                "comic_completed": completed,
                "tenant": tenant,
            },
            "$setOnInsert": {"student_id": student_id, "daily_id": daily_id},
        },
        upsert=True,
    )

    xp_earned = 0
    if completed:
        progress = await db.student_daily_progress.find_one({"student_id": student_id, "daily_id": daily_id})
        if progress and not progress.get("comic_xp_awarded"):
            xp_earned = base_xp
            await db.student_daily_progress.update_one(
                {"student_id": student_id, "daily_id": daily_id},
                {"$set": {"comic_xp_awarded": True}},
            )

    return {"status": "ok", "panels_read": panels_read, "total_panels": total_panels, "xp_earned": xp_earned}


# ---------- Provider comparison (internal/demo eval) ----------

class CompareRequest(BaseModel):
    daily_id:      str | None = None
    transcript_id: str | None = None
    grade:         int | None = None
    force:         bool = False


@router.post("/compare/generate")
async def generate_provider_comparison(req: CompareRequest, tenant: str = Depends(get_tenant)):
    """
    Internal eval: generate a summary + story from EACH transcription provider
    (faster_whisper / sarvam / gemini), holding topic + NCERT context constant.
    Stored in `provider_comparisons`. Provide transcript_id (preferred) or daily_id.
    """
    from app.services.provider_comparison_service import generate_comparison
    try:
        doc = await generate_comparison(
            transcript_id=req.transcript_id,
            daily_id=req.daily_id,
            grade=req.grade,
            force=req.force,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return doc


@router.get("/compare")
async def get_provider_comparison(daily_id: str | None = None, transcript_id: str | None = None):
    """Return a cached provider comparison by daily_id or transcript_id."""
    from app.services.provider_comparison_service import get_comparison
    doc = await get_comparison(daily_id=daily_id, transcript_id=transcript_id)
    return doc or {"providers": None}


# ---------- Animated story endpoints (5-rule engine) ----------

class StoryRequest(BaseModel):
    daily_id:      str
    student_id:    str
    grade:         int
    personality:   str = "curious"
    force:         bool = False
    summary_focus: list[str] = []


@router.get("/story")
async def get_existing_story(
    daily_id:   str,
    student_id: str,
):
    """Check cache for an existing generated story. Returns story or null."""
    db = await get_db()
    doc = await db.story_generations.find_one(
        {"daily_id": daily_id, "student_id": student_id},
        {"_id": 0},
    )
    if doc:
        return {
            "story":        doc["story"],
            "from_cache":   True,
            "generated_at": doc.get("generated_at", ""),
        }
    return {"story": None, "from_cache": False}


@router.post("/story/generate")
async def generate_story_endpoint(
    req: StoryRequest,
    tenant: str = Depends(get_tenant),
):
    """Generate (or return cached) animated comic story for a daily class."""
    db = await get_db()

    if not req.force:
        existing = await db.story_generations.find_one(
            {"daily_id": req.daily_id, "student_id": req.student_id}
        )
        if existing:
            return {"story": existing["story"], "from_cache": True}

    # Fetch daily class
    if not ObjectId.is_valid(req.daily_id):
        raise HTTPException(status_code=400, detail="Invalid daily_id")
    daily = await db.classes_daily.find_one({"_id": ObjectId(req.daily_id)})
    if not daily:
        raise HTTPException(status_code=404, detail="Daily class not found")

    topics = [t for t in (daily.get("topics") or []) if t]
    if not topics:
        raise HTTPException(status_code=400, detail="No topics set — ask your teacher to configure today's lesson")

    topic = ", ".join(topics)
    subject = daily.get("subject", "Science")
    class_no = daily.get("class_no", req.grade)

    # Fetch transcript if available
    transcript_doc = await db.transcripts.find_one({"daily_id": req.daily_id})
    transcript = transcript_doc.get("text", "") if transcript_doc else ""

    # Fetch NCERT content for the topic
    ncert_content = ""
    chapter = await db.curriculum_chapters.find_one({
        "class": class_no,
        "subject": {"$regex": f"^{subject}$", "$options": "i"},
    })
    if chapter:
        concepts = "\n".join(
            f"- {c.get('name','')}: {c.get('explanation','')}"
            for c in chapter.get("concepts", [])[:6]
        )
        ncert_content = (
            f"Chapter: {chapter.get('chapter_title','')}\n"
            f"Summary: {chapter.get('chapter_summary','')}\n"
            f"Concepts:\n{concepts}"
        )

    from app.services.story_service import generate_story
    try:
        story, gen_ms = await generate_story(
            topic=topic,
            subject=subject,
            grade=class_no,
            transcript=transcript,
            ncert_content=ncert_content,
            personality=req.personality,
            summary_focus=req.summary_focus,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    now = datetime.now(timezone.utc).isoformat()
    await db.story_generations.replace_one(
        {"daily_id": req.daily_id, "student_id": req.student_id},
        {
            "daily_id":      req.daily_id,
            "student_id":    req.student_id,
            "grade":         class_no,
            "personality":   req.personality,
            "story":         story,
            "generated_at":  now,
            "generation_ms": gen_ms,
            "tenant":        tenant,
        },
        upsert=True,
    )

    logger.info(f"[STORY] Saved story for daily_id={req.daily_id} topic='{topic}' in {gen_ms}ms")
    return {"story": story, "from_cache": False, "generated_at": now, "generation_ms": gen_ms}


# ---------- Guru-Shishya dialogue story endpoints (parallel format) ----------

class GuruStoryRequest(BaseModel):
    daily_id:      str
    student_id:    str
    grade:         int
    personality:   str = "curious"
    force:         bool = False
    summary_focus: list[str] = []


@router.get("/guru-story")
async def get_existing_guru_story(
    daily_id:   str,
    student_id: str,
):
    """Check cache for an existing generated Guru-Shishya story. Returns story or null."""
    db = await get_db()
    doc = await db.guru_shishya_stories.find_one(
        {"daily_id": daily_id, "student_id": student_id},
        {"_id": 0},
    )
    if doc:
        return {
            "story":        doc["story"],
            "from_cache":   True,
            "generated_at": doc.get("generated_at", ""),
        }
    return {"story": None, "from_cache": False}


@router.post("/guru-story/generate")
async def generate_guru_story_endpoint(
    req: GuruStoryRequest,
    tenant: str = Depends(get_tenant),
):
    """Generate (or return cached) Guru-Shishya dialogue story for a daily class."""
    db = await get_db()

    if not req.force:
        existing = await db.guru_shishya_stories.find_one(
            {"daily_id": req.daily_id, "student_id": req.student_id}
        )
        if existing:
            return {"story": existing["story"], "from_cache": True}

    if not ObjectId.is_valid(req.daily_id):
        raise HTTPException(status_code=400, detail="Invalid daily_id")
    daily = await db.classes_daily.find_one({"_id": ObjectId(req.daily_id)})
    if not daily:
        raise HTTPException(status_code=404, detail="Daily class not found")

    topics = [t for t in (daily.get("topics") or []) if t]
    if not topics:
        raise HTTPException(
            status_code=400,
            detail="No topics set — ask your teacher to configure today's lesson",
        )

    topic = ", ".join(topics)
    subject = daily.get("subject", "Science")
    class_no = daily.get("class_no", req.grade)

    transcript_doc = await db.transcripts.find_one({"daily_id": req.daily_id})
    transcript = transcript_doc.get("text", "") if transcript_doc else ""

    ncert_content = ""
    chapter = await db.curriculum_chapters.find_one({
        "class": class_no,
        "subject": {"$regex": f"^{subject}$", "$options": "i"},
    })
    if chapter:
        concepts = "\n".join(
            f"- {c.get('name','')}: {c.get('explanation','')}"
            for c in chapter.get("concepts", [])[:6]
        )
        ncert_content = (
            f"Chapter: {chapter.get('chapter_title','')}\n"
            f"Summary: {chapter.get('chapter_summary','')}\n"
            f"Concepts:\n{concepts}"
        )

    from app.services.guru_shishya_service import generate_guru_shishya_story
    try:
        story, gen_ms = await generate_guru_shishya_story(
            topic=topic,
            subject=subject,
            grade=class_no,
            transcript=transcript,
            ncert_content=ncert_content,
            personality=req.personality,
            summary_focus=req.summary_focus,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    now = datetime.now(timezone.utc).isoformat()
    await db.guru_shishya_stories.replace_one(
        {"daily_id": req.daily_id, "student_id": req.student_id},
        {
            "daily_id":      req.daily_id,
            "student_id":    req.student_id,
            "grade":         class_no,
            "personality":   req.personality,
            "story":         story,
            "generated_at":  now,
            "generation_ms": gen_ms,
            "tenant":        tenant,
        },
        upsert=True,
    )

    logger.info(
        f"[GURU_STORY] Saved story for daily_id={req.daily_id} topic='{topic}' in {gen_ms}ms"
    )
    return {"story": story, "from_cache": False, "generated_at": now, "generation_ms": gen_ms}


# ---------- SILF revision-story endpoints (exam-centric, NCERT-figure-grounded) ----------
# Parallel to /story — the existing comic story is untouched. Visuals here are the
# real NCERT textbook figures ingested into ncert_figures (see ncert_ingest_service).

class SilfStoryRequest(BaseModel):
    daily_id:         str
    student_id:       str
    grade:            int
    chapter_key:      str | None = None   # optional override; else resolved from curriculum_chapters
    narrative_format: str | None = None   # detective | broken_world | race | apprentice (else subject default)
    force:            bool = False


@router.get("/silf-story/formats")
async def list_silf_formats():
    """The narrative formats a student can choose from (id + label + description)."""
    from app.services.silf_story_service import FORMATS, resolve_format
    descriptions = {
        "detective":    "Crack the case — clues lead you to the concept.",
        "broken_world": "Something's broken. Use the concept to fix it.",
        "race":         "Beat the clock — use the concept to win in time.",
        "apprentice":   "Travel back and help the scientist discover it.",
    }
    return {
        "formats": [
            {"id": fid, "label": f["label"], "description": descriptions.get(fid, "")}
            for fid, f in FORMATS.items()
        ],
        "default_by_subject": {
            s: resolve_format(None, s) for s in ("Science", "Mathematics", "Physics", "Chemistry", "Biology")
        },
    }


async def _resolve_chapter_key(db, *, class_no: int, subject: str, override: str | None) -> str | None:
    if override:
        return override
    chapter = await db.curriculum_chapters.find_one(
        {"class": class_no, "subject": {"$regex": f"^{subject}$", "$options": "i"}},
        {"chapter_key": 1},
    )
    return chapter.get("chapter_key") if chapter else None


@router.get("/silf-story")
async def get_existing_silf_story(daily_id: str, student_id: str, narrative_format: str | None = None):
    """Check cache for an existing SILF story (optionally for a specific format)."""
    db = await get_db()
    q = {"daily_id": daily_id, "student_id": student_id}
    if narrative_format:
        q["narrative_format"] = narrative_format
    doc = await db.silf_story_generations.find_one(q, {"_id": 0})
    if doc:
        return {
            "story": doc["story"],
            "from_cache": True,
            "generated_at": doc.get("generated_at", ""),
            "narrative_format": doc.get("narrative_format"),
        }
    return {"story": None, "from_cache": False}


@router.post("/silf-story/generate")
async def generate_silf_story_endpoint(
    req: SilfStoryRequest,
    tenant: str = Depends(get_tenant),
):
    """Generate (or return cached) SILF revision story grounded in real NCERT figures."""
    db = await get_db()

    if not ObjectId.is_valid(req.daily_id):
        raise HTTPException(status_code=400, detail="Invalid daily_id")
    daily = await db.classes_daily.find_one({"_id": ObjectId(req.daily_id)})
    if not daily:
        raise HTTPException(status_code=404, detail="Daily class not found")

    topics = [t for t in (daily.get("topics") or []) if t]
    if not topics:
        raise HTTPException(status_code=400, detail="No topics set — ask your teacher to configure today's lesson")

    topic = ", ".join(topics)
    subject = daily.get("subject", "Science")
    class_no = daily.get("class_no", req.grade)

    # Resolve the chosen narrative format (or the best default for the subject).
    from app.services.silf_story_service import resolve_format
    fmt_id = resolve_format(req.narrative_format, subject)

    # Cache is per (daily, student, format) — switching format generates a fresh story.
    if not req.force:
        existing = await db.silf_story_generations.find_one(
            {"daily_id": req.daily_id, "student_id": req.student_id, "narrative_format": fmt_id}
        )
        if existing:
            return {"story": existing["story"], "from_cache": True}

    transcript_doc = await db.transcripts.find_one({"daily_id": req.daily_id})
    transcript = transcript_doc.get("text", "") if transcript_doc else ""

    chapter_key = await _resolve_chapter_key(db, class_no=class_no, subject=subject, override=req.chapter_key)

    # NCERT source-of-truth: prefer ingested chapter text, fall back to concept snippet.
    ncert_content = ""
    if chapter_key:
        pages = await db.ncert_chapter_text.find(
            {"chapter_key": chapter_key}, {"text": 1, "page": 1, "_id": 0}
        ).sort("page", 1).to_list(length=None)
        ncert_content = "\n".join(p.get("text", "") for p in pages)[:8000]
    if not ncert_content:
        chapter = await db.curriculum_chapters.find_one(
            {"class": class_no, "subject": {"$regex": f"^{subject}$", "$options": "i"}}
        )
        if chapter:
            concepts = "\n".join(
                f"- {c.get('name','')}: {c.get('explanation','')}"
                for c in chapter.get("concepts", [])[:6]
            )
            ncert_content = (
                f"Chapter: {chapter.get('chapter_title','')}\n"
                f"Summary: {chapter.get('chapter_summary','')}\n"
                f"Concepts:\n{concepts}"
            )

    # Figure catalog the LLM may select from (no image bytes in the prompt).
    figure_catalog = []
    if chapter_key:
        figs = await db.ncert_figures.find(
            {"chapter_key": chapter_key},
            {"_id": 1, "figure_number": 1, "caption": 1},
        ).to_list(length=None)
        figs.sort(key=lambda f: [int(x) for x in str(f.get("figure_number", "0")).split(".") if x.isdigit()] or [0])
        figure_catalog = [
            {"id": f["_id"], "figure_number": f.get("figure_number"), "caption": f.get("caption", "")}
            for f in figs
        ]

    from app.services.silf_story_service import generate_silf_story
    from app.services.silf_verifier_service import verify_silf_story
    from app.services.llm_cost import usage_entry, summarize
    catalog_ids = {f["id"] for f in figure_catalog}

    # Accumulate every LLM call's token usage so we can store the cost of this story.
    cost_calls: list[dict] = []

    def _take(d, label):
        u = d.pop("_usage", None) if isinstance(d, dict) else None
        if u:
            cost_calls.append(usage_entry(label, u.get("model"), u.get("in", 0), u.get("out", 0)))

    async def _gen():
        return await generate_silf_story(
            topic=topic, subject=subject, grade=class_no, chapter_key=chapter_key or "",
            transcript=transcript, ncert_content=ncert_content, figure_catalog=figure_catalog,
            narrative_format=fmt_id,
        )

    try:
        story, gen_ms = await _gen()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    _take(story, "story")

    # Independent verification (deterministic checks + fresh LLM judge). Verify the
    # TEXT story before spending animation cost; regenerate once if it fails the bar.
    verification = await verify_silf_story(
        story, topic=topic, subject=subject, grade=class_no,
        ncert_content=ncert_content, catalog_ids=catalog_ids,
    )
    _take(verification, "verify")
    if not verification.get("passed"):
        logger.info(f"[SILF_STORY] verification failed ({verification['overall_score']}/10) — regenerating once")
        try:
            story2, gen_ms2 = await _gen()
            _take(story2, "story:retry")
            v2 = await verify_silf_story(
                story2, topic=topic, subject=subject, grade=class_no,
                ncert_content=ncert_content, catalog_ids=catalog_ids,
            )
            _take(v2, "verify:retry")
            gen_ms += gen_ms2
            # Prefer a really-judged candidate; a defaulted (judge-failed) score must
            # never beat a real one. Among equal judge-status, take the higher score.
            cur_ok, new_ok = verification.get("judge_ok"), v2.get("judge_ok")
            if (new_ok and not cur_ok) or (
                new_ok == cur_ok and v2.get("overall_score", 0) > verification.get("overall_score", 0)
            ):
                story, verification = story2, v2
        except Exception as e:
            logger.warning(f"[SILF_STORY] regeneration failed: {e}")
    story["verification"] = verification

    # Generate all left-panel visuals concurrently: scene panels (steps 1-2) + the
    # mechanism animation (step 3). The NCERT figure (step 4) is served separately.
    try:
        from app.services.silf_animation_service import generate_silf_animation, generate_scene_panel

        async def _visual(step):
            t = step.get("asset_type")
            if t == "ANIMATED_SIM" and step.get("animation_brief"):
                return await generate_silf_animation(
                    topic=topic, subject=subject, grade=class_no,
                    animation_brief=step["animation_brief"], summary_text=ncert_content[:1500],
                )
            if t == "SCENE_PANEL" and step.get("panel_brief"):
                return await generate_scene_panel(
                    topic=topic, subject=subject, grade=class_no,
                    panel_brief=step["panel_brief"], summary_text=ncert_content[:1500],
                )
            return None

        targets = [s for s in story.get("storyboard_steps", []) if s.get("asset_type") in ("ANIMATED_SIM", "SCENE_PANEL")]
        results = await asyncio.gather(*[_visual(s) for s in targets], return_exceptions=True)
        for step, res in zip(targets, results):
            html, vusage = (res if isinstance(res, tuple) else (None, None))
            if vusage:
                kind = "animation" if step["asset_type"] == "ANIMATED_SIM" else "scene_panel"
                cost_calls.append(usage_entry(f"{kind}:step{step.get('step_number')}", vusage.get("model"), vusage.get("in", 0), vusage.get("out", 0)))
            if html and step["asset_type"] == "ANIMATED_SIM":
                step["animation_html"] = html
            elif html and step["asset_type"] == "SCENE_PANEL":
                step["panel_html"] = html
            # if a visual fails, the step keeps has_visual_asset but no html → FE shows
            # the avatar-in-scene fallback, so the split layout never looks broken.
    except Exception as e:
        logger.warning(f"[SILF_STORY] visual generation failed: {e}")

    # Roll up the full cost of generating this one story (all LLM calls).
    cost = summarize(cost_calls)
    story["cost"] = cost

    now = datetime.now(timezone.utc).isoformat()
    await db.silf_story_generations.replace_one(
        {"daily_id": req.daily_id, "student_id": req.student_id, "narrative_format": fmt_id},
        {
            "daily_id":         req.daily_id,
            "student_id":       req.student_id,
            "grade":            class_no,
            "chapter_key":      chapter_key,
            "narrative_format": fmt_id,
            "story":            story,
            "cost":             cost,
            "generated_at":     now,
            "generation_ms":    gen_ms,
            "tenant":           tenant,
        },
        upsert=True,
    )

    v = story.get("verification") or {}
    vs = v.get("scores", {})
    logger.info(
        f"[SILF_STORY] Saved daily_id={req.daily_id} topic='{topic}' "
        f"chapter_key={chapter_key} figures={len(figure_catalog)} in {gen_ms}ms "
        f"| INDEPENDENT overall={v.get('overall_score')}/10 passed={v.get('passed')} "
        f"| COST calls={cost['calls']} tokens={cost['total_tokens']} "
        f"~${cost['est_usd']} (~₹{cost['est_inr']})"
    )
    return {"story": story, "from_cache": False, "generated_at": now, "generation_ms": gen_ms, "verification": v, "cost": cost}
