from fastapi import APIRouter, Depends, HTTPException, Query
from ..core.security import api_key_guard
from ..db.mongo import get_db
from ..models.schemas import Story
from ..services.ai import generate_story
from ..services.rag import answer_with_rag

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(api_key_guard)])

@router.get("/rag/answer")
async def rag_answer(query: str, class_no: int, subject: str):
    answer = await answer_with_rag(query, class_no, subject)
    return {"answer": answer}

@router.post("/story", response_model=Story)
async def story_for_student(daily_id: str, student_id: str):
    db = await get_db()
    d = await db.classes_daily.find_one({"_id":{"$oid": daily_id}})
    s = await db.students.find_one({"student_id": student_id})
    topic = ", ".join(d.get("topics", [])) if d else "today's topic"
    persona = s.get("persona") if s else None
    text = await generate_story(topic, persona)
    res = await db.stories.insert_one({"daily_id": daily_id, "student_id": student_id, "persona_used": persona, "text": text})
    return Story(id=str(res.inserted_id), daily_id=daily_id, student_id=student_id, persona_used=persona, text=text)




async def generate_story(topic: str, persona: dict | None, prefs: "ContentPrefs | None" = None) -> str:
    client = get_client()

    # Build a compact style string from prefs
    style_parts = []
    if prefs:
        style_parts.append(f"Story format: {prefs.story_format}")
        style_parts.append(f"Length: {prefs.story_length}")
        style_parts.append(f"Tone: {prefs.tone}, Humor: {prefs.humor_level}")
        style_parts.append(f"Examples: {', '.join(prefs.examples_type) or 'none'}")
        if prefs.reference_figures:
            style_parts.append(f"Reference figures: {', '.join(prefs.reference_figures)}")
        style_parts.append(f"Language: {prefs.language}")
        style_parts.append(f"Steps: {'yes' if prefs.include_steps else 'no'}")
        style_parts.append(f"Summary: {prefs.include_summary}")
        style_parts.append(f"Diagrams: {prefs.diagram_preference}")
        style_parts.append(f"Explain as: {prefs.explanation_granularity} in {prefs.explanation_format}")
    style = " | ".join(style_parts)

    prompt = (
        f"Create a {prefs.story_format if prefs else 'fiction'} story that teaches: {topic}. "
        f"Prefer the child's interests if given. Keep it safe for ages 8–12.\n\n"
        f"Presentation prefs: {style or 'default'}"
    )

    resp = client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role":"system","content":"You create kid-friendly educational stories. Respect the given presentation preferences strictly."},
            {"role":"user","content":prompt},
        ],
        temperature=0.6,
    )
    return resp.choices[0].message.content.strip()


from ..models.schemas import Story, ContentPrefs

def _merge_prefs(school_doc, student_doc) -> ContentPrefs | None:
    school_p = school_doc.get("content_prefs") if school_doc else None
    student_p = student_doc.get("content_prefs") if student_doc else None
    if not school_p and not student_p:
        return None
    base = ContentPrefs(**school_p) if school_p else ContentPrefs()
    return ContentPrefs(**{**base.model_dump(), **(student_p or {})})

@router.post("/story", response_model=Story)
async def story_for_student(daily_id: str, student_id: str):
    db = await get_db()
    d = await db.classes_daily.find_one({"_id":{"$oid": daily_id}})
    s = await db.students.find_one({"student_id": student_id})
    school = await db.schools.find_one({"tenant": s.get("school_tenant")}) if s and s.get("school_tenant") else None

    topic = ", ".join(d.get("topics", [])) if d else "today's topic"
    prefs = _merge_prefs(school, s)
    text = await generate_story(topic, s.get("persona") if s else None, prefs=prefs)
    res = await db.stories.insert_one({
        "daily_id": daily_id, "student_id": student_id,
        "persona_used": (s.get("persona") if s else None),
        "text": text
    })
    return Story(id=str(res.inserted_id), daily_id=daily_id, student_id=student_id, persona_used=s.get("persona") if s else None, text=text)
    from ..models.schemas import Story, ContentPrefs

def _merge_prefs(school_doc, student_doc) -> ContentPrefs | None:
    school_p = school_doc.get("content_prefs") if school_doc else None
    student_p = student_doc.get("content_prefs") if student_doc else None
    if not school_p and not student_p:
        return None
    base = ContentPrefs(**school_p) if school_p else ContentPrefs()
    return ContentPrefs(**{**base.model_dump(), **(student_p or {})})

@router.post("/story", response_model=Story)
async def story_for_student(daily_id: str, student_id: str):
    db = await get_db()
    d = await db.classes_daily.find_one({"_id":{"$oid": daily_id}})
    s = await db.students.find_one({"student_id": student_id})
    school = await db.schools.find_one({"tenant": s.get("school_tenant")}) if s and s.get("school_tenant") else None

    topic = ", ".join(d.get("topics", [])) if d else "today's topic"
    prefs = _merge_prefs(school, s)
    text = await generate_story(topic, s.get("persona") if s else None, prefs=prefs)
    res = await db.stories.insert_one({
        "daily_id": daily_id, "student_id": student_id,
        "persona_used": (s.get("persona") if s else None),
        "text": text
    })
    return Story(id=str(res.inserted_id), daily_id=daily_id, student_id=student_id, persona_used=s.get("persona") if s else None, text=text)
