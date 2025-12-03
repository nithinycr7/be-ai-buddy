from fastapi import APIRouter, Depends, HTTPException, Query
from ..core.security import api_key_guard
from ..db.mongo import get_db
from ..models.schemas import Story, ContentPrefs
from ..services.ai import get_client
from ..services.rag import answer_with_rag
from ..core.config import settings

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(api_key_guard)])

@router.get("/rag/answer")
async def rag_answer(query: str, class_no: int, subject: str):
    answer = await answer_with_rag(query, class_no, subject)
    return {"answer": answer}

async def generate_story(topic: str, persona: str | dict | None, prefs: "ContentPrefs | None" = None) -> str:
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

    prompt = f"Create a short motivational story (<=200 words) that teaches the concept: {topic}. "
    
    if persona:
        if isinstance(persona, dict):
            # Format structured persona
            style_desc = (
                f"Role: {persona.get('character_role', 'Explorer')}, "
                f"Tone: {persona.get('story_tone', 'Adventurous')}, "
                f"Themes: {', '.join(persona.get('themes', []))}, "
                f"Difficulty: {persona.get('difficulty', 'Balanced')}, "
                f"Format: {persona.get('format', 'Comic-style')}"
            )
            prompt += f"Style for a child who likes: {style_desc}. "
        else:
            # Legacy string persona
            prompt += f"Style for a child who likes: {persona}. "

    prompt += (
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

def _merge_prefs(school_doc, student_doc) -> ContentPrefs | None:
    school_p = school_doc.get("content_prefs") if school_doc else None
    student_p = student_doc.get("content_prefs") if student_doc else None
    if not school_p and not student_p:
        return None
    base = ContentPrefs(**school_p) if school_p else ContentPrefs()
    return ContentPrefs(**{**base.model_dump(), **(student_p or {})})

from bson import ObjectId

@router.post("/story", response_model=Story)
async def story_for_student(daily_id: str, student_id: str):
    db = await get_db()
    if not ObjectId.is_valid(daily_id):
         raise HTTPException(status_code=400, detail="Invalid daily_id format")
    
    d = await db.classes_daily.find_one({"_id": ObjectId(daily_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Daily class not found")
    s = await db.students.find_one({"student_id": student_id})
    school = await db.schools.find_one({"tenant": s.get("school_tenant")}) if s and s.get("school_tenant") else None

    # Get current persona
    persona_data = s.get("story_persona") if s else None
    
    # Check for existing story
    existing_story = await db.stories.find_one({
        "daily_id": daily_id,
        "student_id": student_id
    }, sort=[("created_at", -1)]) # Get latest if multiple exist

    if existing_story:
        # Compare personas (handle None vs missing key differences if any)
        # We assume persona_used is stored exactly as it was in student profile
        prev_persona = existing_story.get("persona_used")
        
        # If personas match, return existing story without regenerating
        if prev_persona == persona_data:
            # Ensure ID is string
            if "_id" in existing_story:
                existing_story["id"] = str(existing_story["_id"])
            # Ensure persona_used is string for response model if it's a dict
            if isinstance(existing_story.get("persona_used"), dict):
                existing_story["persona_used"] = str(existing_story["persona_used"])
            return Story(**existing_story)

    # If no story or persona changed, generate new one
    topic = ", ".join(d.get("topics", [])) if d else "today's topic"
    prefs = _merge_prefs(school, s)
    
    text, tokens_used = await generate_story(topic, persona_data, prefs=prefs)
    
    from datetime import datetime
    now = datetime.utcnow().isoformat() + "Z"

    # Calculate generation count for this persona
    count = await db.stories.count_documents({
        "daily_id": daily_id,
        "student_id": student_id,
        "persona_used": persona_data
    })
    generation_count = count + 1

    res = await db.stories.insert_one({
        "daily_id": daily_id, "student_id": student_id,
        "persona_used": persona_data, # Store the structured persona
        "text": text,
        "tokens_used": tokens_used,
        "generation_count": generation_count,
        "created_at": now
    })
    
    story_id = str(res.inserted_id)
    
    # Auto-track story generation in progress
    progress = await db.student_progress.find_one({
        "student_id": student_id,
        "daily_id": daily_id
    })
    
    if not progress:
        # Create new progress document
        progress = {
            "student_id": student_id,
            "daily_id": daily_id,
            "tenant": d.get("tenant", "demo-school"),
            "date": d["date"],
            "class_no": d["class_no"],
            "section": d["section"],
            "subject": d["subject"],
            "summary_viewed": False,
            "story_generated": False,
            "quiz_taken": False,
            "quiz_attempts": 0,
            "completion_percentage": 0.0,
            "is_completed": False,
            "created_at": now,
            "updated_at": now
        }
    
    # Update story fields
    progress["story_generated"] = True
    progress["story_id"] = story_id
    progress["story_generated_at"] = now
    progress["updated_at"] = now
    
    # Recalculate completion
    completion = 0.0
    if progress.get("summary_viewed"):
        completion += 25.0
    if progress.get("story_generated"):
        completion += 25.0
    if progress.get("quiz_best_score") is not None:
        completion += (progress["quiz_best_score"] / 100.0) * 50.0
    
    progress["completion_percentage"] = completion
    progress["is_completed"] = completion >= 75.0
    
    if progress["is_completed"] and not progress.get("completed_at"):
        progress["completed_at"] = now
    
    # Upsert progress
    await db.student_progress.update_one(
        {"student_id": student_id, "daily_id": daily_id},
        {"$set": progress},
        upsert=True
    )
    
    # Convert persona_data to string for response model if needed
    persona_str = str(persona_data) if persona_data else None
    
    return Story(
        id=story_id, 
        daily_id=daily_id, 
        student_id=student_id, 
        persona_used=persona_str, 
        text=text,
        tokens_used=tokens_used,
        generation_count=generation_count
    )
