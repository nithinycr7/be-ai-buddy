"""
Generated-content business logic: comic / story / guru-shishya / SILF stories.
router → ContentService → repositories (+ LLM generation/verification services).

The service holds the fetch-context + generate + cache-write orchestration and
raises domain exceptions; it never touches Motor and never raises HTTPException.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import Depends
from pydantic import BaseModel

from ..core.exceptions import AppError, BadRequestError, NotFoundError
from ..core.security import CurrentUser, assert_can_access_student
from ..db.repositories import (
    ComicStoryRepository, get_comic_repo,
    CurriculumRepository, get_curriculum_repo,
    DailyClassRepository, get_daily_repo,
    GuruStoryRepository, get_guru_story_repo,
    NcertContentRepository, get_ncert_content_repo,
    SilfStoryRepository, get_silf_story_repo,
    StoryGenerationRepository, get_story_repo,
    StudentDailyProgressRepository, get_daily_progress_repo,
    StudentRepository, get_student_repo,
    TranscriptRepository, get_transcript_repo,
)

logger = logging.getLogger(__name__)


# ── request schemas (relocated here so the router imports downward) ───────────
class StoryRequest(BaseModel):
    daily_id: str
    student_id: str
    grade: int
    personality: str = "curious"
    force: bool = False
    summary_focus: list[str] = []


class GuruStoryRequest(BaseModel):
    daily_id: str
    student_id: str
    grade: int
    personality: str = "curious"
    force: bool = False
    summary_focus: list[str] = []


class SilfStoryRequest(BaseModel):
    daily_id: str
    student_id: str
    grade: int
    chapter_key: Optional[str] = None
    narrative_format: Optional[str] = None
    force: bool = False


def _validate_daily_id(daily_id: str) -> None:
    if not ObjectId.is_valid(daily_id):
        raise BadRequestError("Invalid daily_id")


def _concept_ncert(chapter: Optional[dict]) -> str:
    if not chapter:
        return ""
    concepts = "\n".join(
        f"- {c.get('name','')}: {c.get('explanation','')}"
        for c in chapter.get("concepts", [])[:6]
    )
    return (
        f"Chapter: {chapter.get('chapter_title','')}\n"
        f"Summary: {chapter.get('chapter_summary','')}\n"
        f"Concepts:\n{concepts}"
    )


class ContentService:
    def __init__(self, *, comic: ComicStoryRepository, daily: DailyClassRepository,
                 students: StudentRepository, progress: StudentDailyProgressRepository,
                 stories: StoryGenerationRepository, guru: GuruStoryRepository,
                 silf: SilfStoryRepository, transcripts: TranscriptRepository,
                 curriculum: CurriculumRepository, ncert: NcertContentRepository):
        self.comic = comic
        self.daily = daily
        self.students = students
        self.progress = progress
        self.stories = stories
        self.guru = guru
        self.silf = silf
        self.transcripts = transcripts
        self.curriculum = curriculum
        self.ncert = ncert

    async def _daily_or_404(self, daily_id: str) -> dict:
        _validate_daily_id(daily_id)
        doc = await self.daily.get(daily_id)
        if not doc:
            raise NotFoundError("Daily class not found")
        return doc

    @staticmethod
    def _topics_or_400(doc: dict) -> tuple[str, str, int]:
        topics = [t for t in (doc.get("topics") or []) if t]
        if not topics:
            raise BadRequestError("No topics set — ask your teacher to configure today's lesson")
        return ", ".join(topics), doc.get("subject", "Science"), doc.get("class_no", 7)

    # ── comic ────────────────────────────────────────────────────────────────
    async def get_or_create_comic(self, *, daily_id: str, student_id: Optional[str],
                                  requester: CurrentUser) -> dict:
        assert_can_access_student(requester, student_id)
        _validate_daily_id(daily_id)

        cached = await self.comic.get_by_daily(daily_id)
        if cached:
            cached["_id"] = str(cached["_id"])
            return cached

        doc = await self.daily.get(daily_id)
        if not doc:
            raise NotFoundError("Daily class not found")
        topics = [t for t in (doc.get("topics") or []) if t]
        if not topics:
            raise BadRequestError("No topics set for this class — ask your teacher to configure today's lesson")
        topic_str = ", ".join(topics)
        subject = doc.get("subject", "Science")
        class_no = doc.get("class_no", 7)

        persona_theme = "adventure"
        if student_id:
            student_doc = await self.students.get(student_id)
            if student_doc:
                persona = student_doc.get("story_persona") or {}
                if isinstance(persona, dict):
                    persona_theme = persona.get("theme") or persona_theme

        from app.services.story_service import generate_comic_story
        story_data = await generate_comic_story(
            topic=topic_str, subject=subject, class_no=class_no, persona_theme=persona_theme)

        story_doc = {"daily_id": daily_id, "subject": subject, "class_no": class_no,
                     "topic": topic_str, **story_data}
        result = await self.comic.create(story_doc)
        story_doc["_id"] = str(result.inserted_id)
        logger.info(f"Generated comic story for daily_id={daily_id} topic='{topic_str}'")
        return story_doc

    async def update_comic_progress(self, *, daily_id: str, student_id: str, panels_read: int,
                                    completed: bool, requester: CurrentUser) -> dict:
        assert_can_access_student(requester, student_id)
        _validate_daily_id(daily_id)

        cached = await self.comic.get_by_daily(daily_id, projection={"panels": 1, "completion_xp": 1})
        total_panels = len(cached.get("panels", [])) if cached else panels_read
        base_xp = (cached or {}).get("completion_xp", 50)

        await self.progress.update_one(
            {"student_id": student_id, "daily_id": daily_id},
            {"$set": {"comic_panels_read": panels_read, "comic_completed": completed},
             "$setOnInsert": {"student_id": student_id, "daily_id": daily_id}},
            upsert=True,
        )

        xp_earned = 0
        if completed:
            prog = await self.progress.get(student_id=student_id, daily_id=daily_id)
            if prog and not prog.get("comic_xp_awarded"):
                xp_earned = base_xp
                await self.progress.update_one(
                    {"student_id": student_id, "daily_id": daily_id},
                    {"$set": {"comic_xp_awarded": True}})

        return {"status": "ok", "panels_read": panels_read, "total_panels": total_panels, "xp_earned": xp_earned}

    # ── story ────────────────────────────────────────────────────────────────
    async def get_story(self, *, daily_id: str, student_id: str, requester: CurrentUser) -> dict:
        assert_can_access_student(requester, student_id)
        doc = await self.stories.get(daily_id=daily_id, student_id=student_id, projection={"_id": 0})
        if doc:
            return {"story": doc["story"], "from_cache": True, "generated_at": doc.get("generated_at", "")}
        return {"story": None, "from_cache": False}

    async def generate_story(self, req: StoryRequest, *, requester: CurrentUser) -> dict:
        assert_can_access_student(requester, req.student_id)
        if not req.force:
            existing = await self.stories.get(daily_id=req.daily_id, student_id=req.student_id)
            if existing:
                return {"story": existing["story"], "from_cache": True}

        daily = await self._daily_or_404(req.daily_id)
        topic, subject, class_no = self._topics_or_400(daily)
        class_no = daily.get("class_no", req.grade)

        transcript_doc = await self.transcripts.get_for_daily(req.daily_id)
        transcript = transcript_doc.get("text", "") if transcript_doc else ""
        ncert_content = _concept_ncert(await self.curriculum.find_chapter(class_no=class_no, subject=subject))

        from app.services.story_service import generate_story
        try:
            story, gen_ms = await generate_story(
                topic=topic, subject=subject, grade=class_no, transcript=transcript,
                ncert_content=ncert_content, personality=req.personality,
                summary_focus=req.summary_focus)
        except Exception as e:
            raise AppError(str(e))

        now = datetime.now(timezone.utc).isoformat()
        await self.stories.upsert(daily_id=req.daily_id, student_id=req.student_id, doc={
            "daily_id": req.daily_id, "student_id": req.student_id, "grade": class_no,
            "personality": req.personality, "story": story,
            "generated_at": now, "generation_ms": gen_ms})
        logger.info(f"[STORY] Saved story for daily_id={req.daily_id} topic='{topic}' in {gen_ms}ms")
        return {"story": story, "from_cache": False, "generated_at": now, "generation_ms": gen_ms}

    # ── guru-shishya ───────────────────────────────────────────────────────────
    async def get_guru(self, *, daily_id: str, student_id: str, requester: CurrentUser) -> dict:
        assert_can_access_student(requester, student_id)
        doc = await self.guru.get(daily_id=daily_id, student_id=student_id, projection={"_id": 0})
        if doc:
            return {"story": doc["story"], "from_cache": True, "generated_at": doc.get("generated_at", "")}
        return {"story": None, "from_cache": False}

    async def generate_guru(self, req: GuruStoryRequest, *, requester: CurrentUser) -> dict:
        assert_can_access_student(requester, req.student_id)
        if not req.force:
            existing = await self.guru.get(daily_id=req.daily_id, student_id=req.student_id)
            if existing:
                return {"story": existing["story"], "from_cache": True}

        daily = await self._daily_or_404(req.daily_id)
        topic, subject, class_no = self._topics_or_400(daily)
        class_no = daily.get("class_no", req.grade)

        transcript_doc = await self.transcripts.get_for_daily(req.daily_id)
        transcript = transcript_doc.get("text", "") if transcript_doc else ""
        ncert_content = _concept_ncert(await self.curriculum.find_chapter(class_no=class_no, subject=subject))

        from app.services.guru_shishya_service import generate_guru_shishya_story
        try:
            story, gen_ms = await generate_guru_shishya_story(
                topic=topic, subject=subject, grade=class_no, transcript=transcript,
                ncert_content=ncert_content, personality=req.personality,
                summary_focus=req.summary_focus)
        except Exception as e:
            raise AppError(str(e))

        now = datetime.now(timezone.utc).isoformat()
        await self.guru.upsert(daily_id=req.daily_id, student_id=req.student_id, doc={
            "daily_id": req.daily_id, "student_id": req.student_id, "grade": class_no,
            "personality": req.personality, "story": story,
            "generated_at": now, "generation_ms": gen_ms})
        logger.info(f"[GURU_STORY] Saved story for daily_id={req.daily_id} topic='{topic}' in {gen_ms}ms")
        return {"story": story, "from_cache": False, "generated_at": now, "generation_ms": gen_ms}

    # ── SILF ───────────────────────────────────────────────────────────────────
    @staticmethod
    def list_silf_formats() -> dict:
        from app.services.silf_story_service import FORMATS, resolve_format
        descriptions = {
            "detective": "Crack the case — clues lead you to the concept.",
            "broken_world": "Something's broken. Use the concept to fix it.",
            "race": "Beat the clock — use the concept to win in time.",
            "apprentice": "Travel back and help the scientist discover it.",
        }
        return {
            "formats": [{"id": fid, "label": f["label"], "description": descriptions.get(fid, "")}
                        for fid, f in FORMATS.items()],
            "default_by_subject": {
                s: resolve_format(None, s) for s in ("Science", "Mathematics", "Physics", "Chemistry", "Biology")},
        }

    async def _resolve_chapter_key(self, *, class_no: int, subject: str, override: Optional[str]) -> Optional[str]:
        if override:
            return override
        chapter = await self.curriculum.find_chapter(class_no=class_no, subject=subject, projection={"chapter_key": 1})
        return chapter.get("chapter_key") if chapter else None

    async def get_silf(self, *, daily_id: str, student_id: str, narrative_format: Optional[str],
                       requester: CurrentUser) -> dict:
        assert_can_access_student(requester, student_id)
        doc = await self.silf.get(daily_id=daily_id, student_id=student_id,
                                  narrative_format=narrative_format, projection={"_id": 0})
        if doc:
            return {"story": doc["story"], "from_cache": True,
                    "generated_at": doc.get("generated_at", ""),
                    "narrative_format": doc.get("narrative_format")}
        return {"story": None, "from_cache": False}

    async def generate_silf(self, req: SilfStoryRequest, *, requester: CurrentUser) -> dict:
        assert_can_access_student(requester, req.student_id)
        daily = await self._daily_or_404(req.daily_id)
        topic, subject, class_no = self._topics_or_400(daily)
        class_no = daily.get("class_no", req.grade)

        from app.services.silf_story_service import resolve_format
        fmt_id = resolve_format(req.narrative_format, subject)

        if not req.force:
            existing = await self.silf.get(daily_id=req.daily_id, student_id=req.student_id, narrative_format=fmt_id)
            if existing:
                return {"story": existing["story"], "from_cache": True}

        transcript_doc = await self.transcripts.get_for_daily(req.daily_id)
        transcript = transcript_doc.get("text", "") if transcript_doc else ""

        chapter_key = await self._resolve_chapter_key(class_no=class_no, subject=subject, override=req.chapter_key)

        ncert_content = ""
        if chapter_key:
            pages = await self.ncert.pages_for_chapter(chapter_key)
            ncert_content = "\n".join(p.get("text", "") for p in pages)[:8000]
        if not ncert_content:
            ncert_content = _concept_ncert(await self.curriculum.find_chapter(class_no=class_no, subject=subject))

        figure_catalog = []
        if chapter_key:
            figs = await self.ncert.figures_for_chapter(chapter_key)
            figs.sort(key=lambda f: [int(x) for x in str(f.get("figure_number", "0")).split(".") if x.isdigit()] or [0])
            figure_catalog = [{"id": f["_id"], "figure_number": f.get("figure_number"),
                               "caption": f.get("caption", "")} for f in figs]

        from app.services.silf_story_service import generate_silf_story
        from app.services.silf_verifier_service import verify_silf_story
        from app.services.llm_cost import usage_entry, summarize
        catalog_ids = {f["id"] for f in figure_catalog}
        cost_calls: list[dict] = []

        def _take(d, label):
            u = d.pop("_usage", None) if isinstance(d, dict) else None
            if u:
                cost_calls.append(usage_entry(label, u.get("model"), u.get("in", 0), u.get("out", 0)))

        async def _gen():
            return await generate_silf_story(
                topic=topic, subject=subject, grade=class_no, chapter_key=chapter_key or "",
                transcript=transcript, ncert_content=ncert_content, figure_catalog=figure_catalog,
                narrative_format=fmt_id)

        try:
            story, gen_ms = await _gen()
        except Exception as e:
            raise AppError(str(e))
        _take(story, "story")

        verification = await verify_silf_story(
            story, topic=topic, subject=subject, grade=class_no,
            ncert_content=ncert_content, catalog_ids=catalog_ids)
        _take(verification, "verify")
        if not verification.get("passed"):
            logger.info(f"[SILF_STORY] verification failed ({verification['overall_score']}/10) — regenerating once")
            try:
                story2, gen_ms2 = await _gen()
                _take(story2, "story:retry")
                v2 = await verify_silf_story(
                    story2, topic=topic, subject=subject, grade=class_no,
                    ncert_content=ncert_content, catalog_ids=catalog_ids)
                _take(v2, "verify:retry")
                gen_ms += gen_ms2
                cur_ok, new_ok = verification.get("judge_ok"), v2.get("judge_ok")
                if (new_ok and not cur_ok) or (
                    new_ok == cur_ok and v2.get("overall_score", 0) > verification.get("overall_score", 0)
                ):
                    story, verification = story2, v2
            except Exception as e:
                logger.warning(f"[SILF_STORY] regeneration failed: {e}")
        story["verification"] = verification

        try:
            from app.services.silf_animation_service import generate_silf_animation, generate_scene_panel

            async def _visual(step):
                t = step.get("asset_type")
                if t == "ANIMATED_SIM" and step.get("animation_brief"):
                    return await generate_silf_animation(
                        topic=topic, subject=subject, grade=class_no,
                        animation_brief=step["animation_brief"], summary_text=ncert_content[:1500])
                if t == "SCENE_PANEL" and step.get("panel_brief"):
                    return await generate_scene_panel(
                        topic=topic, subject=subject, grade=class_no,
                        panel_brief=step["panel_brief"], summary_text=ncert_content[:1500])
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
        except Exception as e:
            logger.warning(f"[SILF_STORY] visual generation failed: {e}")

        cost = summarize(cost_calls)
        story["cost"] = cost

        now = datetime.now(timezone.utc).isoformat()
        await self.silf.upsert(daily_id=req.daily_id, student_id=req.student_id, narrative_format=fmt_id, doc={
            "daily_id": req.daily_id, "student_id": req.student_id, "grade": class_no,
            "chapter_key": chapter_key, "narrative_format": fmt_id, "story": story,
            "cost": cost, "generated_at": now, "generation_ms": gen_ms})

        v = story.get("verification") or {}
        logger.info(
            f"[SILF_STORY] Saved daily_id={req.daily_id} topic='{topic}' "
            f"chapter_key={chapter_key} figures={len(figure_catalog)} in {gen_ms}ms "
            f"| INDEPENDENT overall={v.get('overall_score')}/10 passed={v.get('passed')} "
            f"| COST calls={cost['calls']} tokens={cost['total_tokens']} "
            f"~${cost['est_usd']} (~₹{cost['est_inr']})")
        return {"story": story, "from_cache": False, "generated_at": now,
                "generation_ms": gen_ms, "verification": v, "cost": cost}


def get_content_service(
    comic: ComicStoryRepository = Depends(get_comic_repo),
    daily: DailyClassRepository = Depends(get_daily_repo),
    students: StudentRepository = Depends(get_student_repo),
    progress: StudentDailyProgressRepository = Depends(get_daily_progress_repo),
    stories: StoryGenerationRepository = Depends(get_story_repo),
    guru: GuruStoryRepository = Depends(get_guru_story_repo),
    silf: SilfStoryRepository = Depends(get_silf_story_repo),
    transcripts: TranscriptRepository = Depends(get_transcript_repo),
    curriculum: CurriculumRepository = Depends(get_curriculum_repo),
    ncert: NcertContentRepository = Depends(get_ncert_content_repo),
) -> ContentService:
    return ContentService(
        comic=comic, daily=daily, students=students, progress=progress, stories=stories,
        guru=guru, silf=silf, transcripts=transcripts, curriculum=curriculum, ncert=ncert)
