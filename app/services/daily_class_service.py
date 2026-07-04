"""
Daily-class business logic: create, list, summary regeneration, mindmap, manual
transcript, worker summarize, try-it widget, provider comparison.

router → DailyClassService → repositories (+ LLM/summary/quiz engines). `db` is
injected ONLY to hand to engines that still take a raw client (AutoQuizGenerator,
resolve_grounding, SummaryService, summarize_daily_from_transcript,
insert_daily_transcript). The service never hand-writes a Motor query — those go
through repositories — and never raises HTTPException.
"""
from __future__ import annotations

import asyncio
import json as json_mod
import logging
from datetime import date as dt_date, datetime, timezone

from fastapi import Depends
from pydantic import BaseModel

from app.core.config import settings
from ..core.exceptions import AppError, BadRequestError, NotFoundError
from ..core.security import CurrentUser, assert_can_access_student
from ..db.mongo import get_db
from ..db.repositories import (
    CurriculumRepository, get_curriculum_repo,
    DailyClassRepository, get_daily_repo,
    StudentDailyProgressRepository, get_daily_progress_repo,
    SummaryRepository, get_summary_repo,
    TranscriptRepository, get_transcript_repo,
)
from ..models.schemas import DailyClass, Summary
from ..services.ai import summarize as ai_summarize, get_client, get_chat_client
from ..services.auto_quiz_generator import AutoQuizGenerator

logger = logging.getLogger(__name__)


def _today_iso() -> str:
    return dt_date.today().isoformat()


# ── request schemas (relocated here so the router imports downward) ───────────
class ManualTranscript(BaseModel):
    text: str


class SummarizeRequest(BaseModel):
    daily_id: str | None = None
    class_no: int | None = None
    section: str = "A"
    subject: str | None = None
    date: str | None = None
    topics: list[str] | None = None
    transcript_id: str | None = None
    transcript_text: str | None = None
    chapter_key: str | None = None
    force: bool = False


class DailyTranscriptDoc(BaseModel):
    school_id: str = "evalschool"
    class_id: str
    subject: str = "Science"
    transcript_text: str
    timestamp: int | None = None
    topic: str | None = None
    chapter: str | None = None


class CompareRequest(BaseModel):
    daily_id: str | None = None
    transcript_id: str | None = None
    grade: int | None = None
    force: bool = False


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

SUBJECT_FALLBACKS = {
    "biology": ["Science"], "physics": ["Science"], "chemistry": ["Science"],
    "history": ["Social Science"], "geography": ["Social Science"], "civics": ["Social Science"],
    "math": ["Maths"], "mathematics": ["Maths"],
}

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


def _validate_blocks(data) -> list[dict]:
    """Validate/sanitize LLM JSON (list, {"blocks":[...]}, or nested-list dict)."""
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
    for b in blocks[:10]:
        if not isinstance(b, dict) or "type" not in b:
            continue
        if b["type"] not in VALID_BLOCK_TYPES:
            continue
        cleaned.append(b)

    if "concept" not in {b["type"] for b in cleaned}:
        raise ValueError("Missing required 'concept' block")
    return cleaned


class DailyClassService:
    def __init__(self, *, db, daily: DailyClassRepository, transcripts: TranscriptRepository,
                 summaries: SummaryRepository, curriculum: CurriculumRepository,
                 progress: StudentDailyProgressRepository):
        self.db = db
        self.daily = daily
        self.transcripts = transcripts
        self.summaries = summaries
        self.curriculum = curriculum
        self.progress = progress

    @property
    def tenant(self) -> str:
        return self.daily.tenant

    def _eager_quiz(self, daily_id: str) -> None:
        """Fire-and-forget quiz generation after a summary save (idempotent)."""
        async def _run():
            try:
                quiz = await AutoQuizGenerator(self.db).generate_quiz_for_daily_class(
                    daily_id=daily_id, tenant=self.tenant, force_regenerate=False)
                logger.info(f"[QUIZ_EAGER] {'ready' if quiz else 'no quiz'} for daily_id={daily_id}")
            except Exception as e:
                logger.error(f"[QUIZ_EAGER] failed for daily_id={daily_id}: {e}")
        asyncio.create_task(_run())

    # ── create / list ─────────────────────────────────────────────────────────
    async def create_daily(self, payload: DailyClass) -> DailyClass:
        # mode="json" serialises the `date` field to an ISO string — a plain
        # date object is not bson-encodable (this was a latent create_daily bug).
        data = payload.model_dump(by_alias=True, exclude_none=True, mode="json")
        data["tenant"] = self.tenant
        res = await self.daily.insert_one(data)
        payload.id = str(res.inserted_id)
        payload.tenant = self.tenant
        return payload

    async def list_daily(self, *, class_no: int, section: str, date: str | None,
                         student_id: str | None, demo: bool, requester: CurrentUser) -> list[DailyClass]:
        assert_can_access_student(requester, student_id)
        query: dict = {"class_no": class_no, "section": section}
        if demo and not settings.is_production():
            pass  # demo: all dates
        elif date:
            query["date"] = date
        else:
            query["date"] = _today_iso()

        classes = await self.daily.find_many(query, sort=[("date", -1)], limit=50)

        progress_map = {}
        if student_id and classes:
            ids = [str(c["_id"]) for c in classes]
            rows = await self.progress.find_many({"student_id": student_id, "daily_id": {"$in": ids}})
            progress_map = {p["daily_id"]: p for p in rows}

        results = []
        for doc in classes:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            d_obj = DailyClass(**doc)
            if d_obj.id in progress_map:
                p = progress_map[d_obj.id]
                d_obj.completed = p.get("is_complete", False)
                d_obj.progress = p.get("total_score", 0.0)
            results.append(d_obj)
        return results

    # ── worker: summarize (ai) ─────────────────────────────────────────────────
    async def summarize_daily(self, daily_id: str) -> Summary:
        d = await self.daily.get(daily_id)  # InvalidObjectId -> 400
        if not d:
            raise NotFoundError("Daily class not found")
        t = await self.transcripts.get_for_daily(daily_id)
        base = t["text"] if t else ""
        if d.get("summary"):
            base = d["summary"] + "\n" + base
        text = await ai_summarize(base) if base else ""
        res = await self.summaries.create({"daily_id": daily_id, "text": text})
        return Summary(id=str(res.inserted_id), daily_id=daily_id, text=text)

    # ── regenerate structured summary blocks ────────────────────────────────────
    async def regenerate_summary(self, *, subject: str | None, chapter_number: int,
                                 class_no: int, section: str, daily_id: str | None) -> dict:
        client = get_chat_client()
        prompt_tmpl = SUMMARY_PROMPT

        # PATH A: daily_id provided — use the doc's own data
        if daily_id:
            doc = await self.daily.get(daily_id)  # InvalidObjectId -> 400
            if not doc:
                raise NotFoundError(f"classes_daily {daily_id} not found")

            topic_list = [t for t in (doc.get("topics") or []) if t]
            if not topic_list:
                raise BadRequestError("Document has no topics — set topics before regenerating")

            doc_subject = doc.get("subject", "Science")
            doc_class_no = doc.get("class_no", 7)
            topic_str = ", ".join(topic_list)

            from app.services.ncert.retrieval import resolve_grounding
            grounding = await resolve_grounding(
                self.db, class_no=doc_class_no, subject=doc_subject,
                chapter_key=doc.get("chapter_key"), topics=topic_list,
                topic_ids=[t for t in (doc.get("topic_ids") or []) if t])
            user_content = f"Class {doc_class_no} {doc_subject} — {topic_str}"
            if grounding["content"]:
                user_content += (
                    "\n\nNCERT textbook reference (use for precise facts, definitions, formulas):\n"
                    f"{grounding['content'][:4000]}")

            resp = client.chat.completions.create(
                model=settings.GEMINI_CHAT_MODEL,
                messages=[{"role": "system", "content": prompt_tmpl.format(class_no=doc_class_no)},
                          {"role": "user", "content": user_content}],
                response_format={"type": "json_object"}, temperature=0.3)
            raw = resp.choices[0].message.content
            try:
                blocks = _validate_blocks(json_mod.loads(raw))
            except (json_mod.JSONDecodeError, ValueError) as e:
                logger.error(f"LLM JSON validation failed: {e}\nRaw: {raw[:500]}")
                blocks = [{"type": "concept", "title": topic_str, "content": "Summary not available — please try again."}]

            await self.daily.set_summary_blocks(daily_id, blocks)
            logger.info(f"Regenerated summary for daily_id={daily_id} topic='{topic_str}'")
            self._eager_quiz(daily_id)
            return {"status": "ok", "daily_id": daily_id, "subject": doc_subject, "topic": topic_str,
                    "date": doc.get("date"), "blocks_count": len(blocks),
                    "block_types": [b["type"] for b in blocks]}

        # PATH B: no daily_id — look up curriculum chapter and upsert today
        if not subject:
            raise BadRequestError("subject is required when daily_id is not provided")

        chapter = None
        for s in [subject] + SUBJECT_FALLBACKS.get(subject.lower(), []):
            chapter = await self.curriculum.find_chapter(class_no=class_no, subject=s, chapter_number=chapter_number)
            if chapter:
                break
        if not chapter:
            raise NotFoundError(f"No curriculum found for class {class_no}, {subject}, chapter {chapter_number}")

        concepts_text = "".join(f"\n- {c.get('name','')}: {c.get('explanation','')}" for c in chapter.get("concepts", []))
        textbook_content = (
            f"Chapter: {chapter.get('chapter_title','')}\n"
            f"Summary: {chapter.get('chapter_summary','')}\n"
            f"Key Concepts:{concepts_text}\n"
            f"Formulas/Rules: {', '.join(str(x) for x in chapter.get('key_formulas_or_rules', []))}\n"
            f"Real World Connections: {', '.join(str(x) for x in chapter.get('real_world_connections', []))}")

        resp = client.chat.completions.create(
            model=settings.GEMINI_CHAT_MODEL,
            messages=[{"role": "system", "content": prompt_tmpl.format(class_no=class_no)},
                      {"role": "user", "content": f"Class {class_no} {subject} — {chapter.get('chapter_title','')}\n\n{textbook_content}"}],
            response_format={"type": "json_object"}, temperature=0.3)
        raw = resp.choices[0].message.content
        try:
            blocks = _validate_blocks(json_mod.loads(raw))
        except (json_mod.JSONDecodeError, ValueError) as e:
            logger.error(f"LLM JSON validation failed: {e}\nRaw: {raw[:500]}")
            blocks = [
                {"type": "concept", "title": chapter.get("chapter_title", subject), "content": chapter.get("chapter_summary", "")},
                {"type": "terms", "items": [{"term": c.get("name", ""), "meaning": c.get("explanation", "")[:80]} for c in chapter.get("concepts", [])[:5]]}]

        topics = [c.get("name", "") for c in chapter.get("concepts", [])[:3]]
        target_date = _today_iso()
        resolved_subject = chapter.get("subject", subject)
        result = await self.daily.update_one(
            {"class_no": class_no, "section": section, "subject": resolved_subject, "date": target_date},
            {"$set": {"tenant": self.tenant, "class_no": class_no, "section": section,
                      "subject": resolved_subject, "date": target_date, "topics": topics,
                      "summary_blocks": blocks, "chapter_key": chapter.get("chapter_key")}},
            upsert=True)
        result_id = str(result.upserted_id) if result.upserted_id else "updated"
        logger.info(f"Created summary for {subject} ch{chapter_number} -> {result_id}")
        if result.upserted_id:
            self._eager_quiz(result_id)
        return {"status": "ok", "daily_id": result_id, "subject": resolved_subject,
                "chapter": chapter.get("chapter_title", ""), "date": target_date,
                "blocks_count": len(blocks), "block_types": [b["type"] for b in blocks]}

    # ── mindmap ─────────────────────────────────────────────────────────────────
    async def generate_mindmap(self, *, daily_id: str, force: bool) -> dict:
        from app.services.mindmap import generate_mindmap
        doc = await self.daily.get(daily_id)  # InvalidObjectId -> 400
        if not doc:
            raise NotFoundError(f"classes_daily {daily_id} not found")

        cached = doc.get("mindmap")
        if cached and not force:
            return cached

        blocks = doc.get("summary_blocks") or []
        topics = [t for t in (doc.get("topics") or []) if t]
        topic_str = ", ".join(topics) if topics else doc.get("subject", "Today's Topic")

        tree = await generate_mindmap(
            class_no=doc.get("class_no", 7), subject=doc.get("subject", "Science"),
            topic=topic_str, summary_blocks=blocks)
        await self.daily.update_one({"_id": doc["_id"]}, {"$set": {"mindmap": tree}})
        logger.info(f"Generated mind map for daily_id={daily_id} ({len(tree.get('branches', []))} branches)")
        return tree

    # ── manual transcript ───────────────────────────────────────────────────────
    async def add_manual_transcript(self, *, daily_id: str, text: str) -> dict:
        if not await self.daily.get(daily_id):  # InvalidObjectId -> 400
            raise NotFoundError("Daily class not found")
        now = datetime.now(timezone.utc).isoformat()
        await self.transcripts.upsert_for_daily(daily_id, {
            "text": text, "source": "manual", "tenant": self.tenant, "created_at": now})
        return {"status": "ok", "daily_id": daily_id, "chars": len(text)}

    # ── worker: transcript-doc + unified summarize ──────────────────────────────
    async def create_transcript_doc(self, req: DailyTranscriptDoc) -> dict:
        from app.db.mongo import get_client
        from app.services.summary_blocks import insert_daily_transcript
        if not (req.transcript_text or "").strip():
            raise BadRequestError("transcript_text is required")
        res = await insert_daily_transcript(
            get_client(), school_id=req.school_id, class_id=req.class_id, subject=req.subject,
            transcript_text=req.transcript_text, timestamp=req.timestamp,
            topic=req.topic, chapter=req.chapter)
        return {"status": "ok", **res}

    async def summarize(self, req: SummarizeRequest) -> dict:
        # Mode A: transcript-doc driven
        if req.transcript_id and not req.daily_id and req.class_no is None:
            from app.services.summary_service import SummaryService
            from app.db.mongo import get_client as get_mongo_client
            try:
                result = await SummaryService(get_mongo_client()).generate_summary(req.transcript_id, force=req.force)
            except Exception as e:
                raise AppError(f"Summary generation failed: {e}")
            if not result:
                raise BadRequestError(f"Could not summarize transcript_id={req.transcript_id} (not found / topic not identified)")
            if not result.get("skipped"):
                self._eager_quiz(result["daily_id"])
            return {"status": "ok", **result}

        # Mode B: daily_id / explicit fields / inline text
        from app.services.summary_blocks import summarize_daily_from_transcript
        try:
            result = await summarize_daily_from_transcript(
                self.db, daily_id=req.daily_id, tenant=self.tenant,
                class_no=req.class_no, section=req.section, subject=req.subject,
                date=req.date, topics=req.topics,
                transcript_text=req.transcript_text, transcript_id=req.transcript_id,
                chapter_key=req.chapter_key, force=req.force)
        except ValueError as e:
            raise BadRequestError(str(e))
        except Exception as e:
            raise AppError(f"Summary generation failed: {e}")
        if not result.get("skipped"):
            self._eager_quiz(result["daily_id"])
        return {"status": "ok", **result}

    # ── try-it widget ───────────────────────────────────────────────────────────
    async def generate_widget(self, *, subject: str, chapter_number: int,
                              class_no: int, section: str) -> dict:
        chapter = await self.curriculum.find_chapter(
            class_no=class_no, subject=subject, chapter_number=chapter_number)
        if not chapter:
            raise NotFoundError(f"No curriculum found for class {class_no}, {subject}, chapter {chapter_number}")

        concepts_text = "\n".join(f"- {c.get('name', '')}: {c.get('explanation', '')}" for c in chapter.get("concepts", []))
        formulas = ", ".join(str(x) for x in chapter.get("key_formulas_or_rules", []))
        content = f"""Class {class_no} {subject} — {chapter.get('chapter_title', '')}
Concepts: {concepts_text}
Formulas: {formulas}"""

        client = get_client()
        prompt = WIDGET_PROMPT.replace("{{class_no}}", str(class_no))
        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": content}],
            response_format={"type": "json_object"}, temperature=0.3)
        try:
            widget = json_mod.loads(resp.choices[0].message.content)
            if "widget_type" not in widget:
                raise ValueError("Missing widget_type")
        except (json_mod.JSONDecodeError, ValueError) as e:
            logger.error(f"Widget generation failed: {e}")
            concepts = chapter.get("concepts", [])[:4]
            widget = {
                "widget_type": "drag_sequence",
                "title": f"Order the Key Concepts: {chapter.get('chapter_title', '')}",
                "instruction": "Tap a concept, then tap its correct position.",
                "items": [{"id": str(i + 1), "label": c.get("name", ""), "emoji": "📌", "correct_position": i + 1}
                          for i, c in enumerate(concepts)]}

        today = _today_iso()
        resolved_subject = chapter.get("subject", subject)
        await self.daily.update_one(
            {"class_no": class_no, "section": section, "subject": resolved_subject, "date": today},
            {"$set": {"try_it_widget": widget}}, upsert=False)
        logger.info(f"Widget generated for {subject} ch{chapter_number}: {widget.get('widget_type')}")
        return {"status": "ok", "widget_type": widget.get("widget_type"), "title": widget.get("title"),
                "subject": resolved_subject, "chapter": chapter.get("chapter_title", "")}

    # ── provider comparison (admin eval) ────────────────────────────────────────
    async def generate_comparison(self, req: CompareRequest) -> dict:
        from app.services.provider_comparison_service import generate_comparison
        try:
            return await generate_comparison(
                transcript_id=req.transcript_id, daily_id=req.daily_id,
                grade=req.grade, force=req.force)
        except ValueError as e:
            raise NotFoundError(str(e))
        except Exception as e:
            raise AppError(str(e))

    async def get_comparison(self, *, daily_id: str | None, transcript_id: str | None) -> dict:
        from app.services.provider_comparison_service import get_comparison
        doc = await get_comparison(daily_id=daily_id, transcript_id=transcript_id)
        return doc or {"providers": None}


def get_daily_class_service(
    daily: DailyClassRepository = Depends(get_daily_repo),
    transcripts: TranscriptRepository = Depends(get_transcript_repo),
    summaries: SummaryRepository = Depends(get_summary_repo),
    curriculum: CurriculumRepository = Depends(get_curriculum_repo),
    progress: StudentDailyProgressRepository = Depends(get_daily_progress_repo),
    db=Depends(get_db),
) -> DailyClassService:
    return DailyClassService(db=db, daily=daily, transcripts=transcripts,
                             summaries=summaries, curriculum=curriculum, progress=progress)
