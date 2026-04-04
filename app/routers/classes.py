from __future__ import annotations
# app/routers/classes.py
import logging
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from datetime import date as dt_date
from bson import ObjectId
from app.core.config import settings
from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from ..models.schemas import DailyClass, Summary
from ..services.ai import summarize as ai_summarize, get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/classes", tags=["classes"], dependencies=[Depends(api_key_guard)])

# ---------- helpers ----------
def _today_iso() -> str:
    return dt_date.today().isoformat()

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
SUMMARY_PROMPT = """You are a teacher's assistant. Generate a structured revision summary as JSON.

STRICT RULES:
- Use ONLY facts from the provided content. Do NOT invent information.
- Adapt language for a Class {class_no} student.
- Return ONLY valid JSON, no markdown, no commentary.

CLASS LEVEL GUIDE:
- Class 3-5: Simple everyday words. Max 3 key terms. Max 3 steps. No formulas.
- Class 6-7: Simple scientific vocabulary. Max 5 key terms. Max 5 steps. Basic formulas.
- Class 8-9: Standard terminology. Concise definitions. Include formulas.

REQUIRED JSON FORMAT:
{{
  "blocks": [
    {{
      "type": "concept",
      "title": "One-line topic name",
      "content": "2-3 sentence simple explanation of the core concept"
    }},
    {{
      "type": "terms",
      "items": [
        {{ "term": "Word", "meaning": "Simple one-line meaning" }}
      ]
    }},
    {{
      "type": "steps",
      "title": "How [process] works",
      "steps": ["Step 1 description", "Step 2 description", "Step 3 description"]
    }},
    {{
      "type": "analogy",
      "content": "A memorable real-life comparison to help remember the concept"
    }}
  ]
}}

BLOCK TYPES AVAILABLE (use what fits the subject):
- "concept": Core explanation (REQUIRED, always first)
- "terms": Key vocabulary table (REQUIRED)
- "steps": Ordered process/method steps (for Science processes, Math solving methods)
- "analogy": Memory trick or real-life comparison (REQUIRED, always last)
- "formula": For Math/Science equations: {{"type":"formula","label":"name","expression":"equation","note":"when to use"}}
- "fact": Quick facts list: {{"type":"fact","items":["fact 1","fact 2"]}}
- "timeline": For History/Social: {{"type":"timeline","items":[{{"date":"1857","event":"First War of Independence"}}]}}
- "rule": For English/Math rules: {{"type":"rule","title":"Rule name","content":"The rule explanation","example":"Example"}}

ALSO REQUIRED — "checkpoint" block (ALWAYS include, after analogy):
- Exactly 3 quick questions to test if the student understood the summary
- Questions must ONLY test content from the blocks above (same facts, same terms)
- Mix of question types: true/false, pick-the-right-word, one-line answer
- Format:
  {{"type": "checkpoint", "questions": [
    {{"q": "Question text?", "options": ["A", "B", "C"], "answer": "B", "hint": "Think about..."}},
    {{"q": "True or False: ...", "options": ["True", "False"], "answer": "True", "hint": "Remember..."}},
    {{"q": "Fill: ___ is the green pigment in plants.", "options": ["Chlorophyll", "Glucose", "Oxygen"], "answer": "Chlorophyll", "hint": "It captures..."}}
  ]}}

Return 4-7 blocks total. Always start with "concept", always end with "checkpoint"."""


VALID_BLOCK_TYPES = {"concept", "terms", "steps", "analogy", "formula", "fact", "timeline", "rule", "checkpoint"}


def _validate_blocks(data: dict) -> list[dict]:
    """Validate and sanitize LLM JSON output. Returns cleaned blocks."""
    blocks = data.get("blocks", [])
    if not isinstance(blocks, list) or len(blocks) == 0:
        raise ValueError("No blocks in response")

    cleaned = []
    for b in blocks[:6]:  # Cap at 6 blocks
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
    subject: str = Query(..., description="e.g. Science, Maths, English"),
    chapter_number: int = Query(1, description="Chapter number"),
    class_no: int = Query(7, description="Class number"),
    section: str = Query("A"),
    tenant: str = Depends(get_tenant)
):
    """
    TEST ENDPOINT: Pick a chapter from curriculum_chapters,
    generate structured JSON summary blocks,
    and stamp into classes_daily for frontend rendering.
    """
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

    # 2. Build textbook content
    concepts_text = ""
    for c in chapter.get("concepts", []):
        concepts_text += f"\n- {c.get('name', '')}: {c.get('explanation', '')}"

    textbook_content = f"""Chapter: {chapter.get('chapter_title', '')}
Summary: {chapter.get('chapter_summary', '')}
Key Concepts:{concepts_text}
Formulas/Rules: {', '.join(str(x) for x in chapter.get('key_formulas_or_rules', []))}
Activities: {', '.join(str(x) for x in chapter.get('activities_preserved', []))}
Real World Connections: {', '.join(str(x) for x in chapter.get('real_world_connections', []))}"""

    # 3. Generate structured JSON via LLM
    client = get_client()
    prompt = SUMMARY_PROMPT.format(class_no=class_no)

    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Class {class_no} {subject} — {chapter.get('chapter_title', '')}\n\n{textbook_content}"}
        ],
        response_format={"type": "json_object"},
        temperature=0.3
    )

    raw = resp.choices[0].message.content
    try:
        data = json_mod.loads(raw)
        blocks = _validate_blocks(data)
    except (json_mod.JSONDecodeError, ValueError) as e:
        logger.error(f"LLM JSON validation failed: {e}\nRaw: {raw[:500]}")
        # Fallback: minimal blocks from curriculum data
        blocks = [
            {"type": "concept", "title": chapter.get("chapter_title", subject), "content": chapter.get("chapter_summary", "Summary not available.")},
            {"type": "terms", "items": [{"term": c.get("name", ""), "meaning": c.get("explanation", "")[:80]} for c in chapter.get("concepts", [])[:5]]},
            {"type": "analogy", "content": "Review your textbook for more details on this topic."}
        ]

    # 4. Upsert into classes_daily
    today = _today_iso()
    topics = [c.get("name", "") for c in chapter.get("concepts", [])[:3]]

    result = await db.classes_daily.update_one(
        {"tenant": tenant, "class_no": class_no, "section": section, "subject": chapter.get("subject", subject), "date": today},
        {"$set": {
            "tenant": tenant,
            "class_no": class_no,
            "section": section,
            "subject": chapter.get("subject", subject),
            "date": today,
            "topics": topics,
            "summary_blocks": blocks
        }},
        upsert=True
    )

    daily_id = str(result.upserted_id) if result.upserted_id else "updated"
    logger.info(f"Test summary generated for {subject} ch{chapter_number} -> {daily_id}")

    return {
        "status": "ok",
        "daily_id": daily_id,
        "subject": chapter.get("subject", subject),
        "chapter": chapter.get("chapter_title", ""),
        "date": today,
        "blocks_count": len(blocks),
        "block_types": [b["type"] for b in blocks]
    }


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
