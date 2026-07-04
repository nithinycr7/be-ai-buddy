from __future__ import annotations
# app/routers/classes.py — HTTP layer only. Logic lives in DailyClassService / ContentService.
from fastapi import APIRouter, Depends, Body, Query

from ..core.security import api_key_guard, require_role, get_current_user, CurrentUser
from ..services.content_service import (
    ContentService, get_content_service,
    StoryRequest, GuruStoryRequest, SilfStoryRequest,
)
from ..services.daily_class_service import (
    DailyClassService, get_daily_class_service,
    ManualTranscript, SummarizeRequest, DailyTranscriptDoc, CompareRequest,
)
from ..models.schemas import DailyClass, Summary

# User endpoints are gated per-endpoint with require_role(...). The 3 machine-to-machine
# WORKER endpoints (transcript-doc, summarize, {id}/summarize) carry api_key_guard.
router = APIRouter(prefix="/classes", tags=["classes"])


# ---------- daily class CRUD + summary/mindmap/transcript/widget ----------
@router.post("/daily", response_model=DailyClass, status_code=201)
async def create_daily(
    payload: DailyClass,
    service: DailyClassService = Depends(get_daily_class_service),
    user: CurrentUser = Depends(require_role("teacher", "admin")),
):
    return await service.create_daily(payload)


@router.post("/daily/{daily_id}/summarize", response_model=Summary)
async def summarize_daily(
    daily_id: str,
    service: DailyClassService = Depends(get_daily_class_service),
    _: bool = Depends(api_key_guard),
):
    return await service.summarize_daily(daily_id)


@router.get("/daily", response_model=list[DailyClass])
async def list_daily_classes(
    class_no: int,
    section: str,
    date: str | None = None,
    student_id: str | None = None,
    demo: bool = False,
    service: DailyClassService = Depends(get_daily_class_service),
    user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin")),
):
    return await service.list_daily(
        class_no=class_no, section=section, date=date,
        student_id=student_id, demo=demo, requester=user)


@router.post("/daily/regenerate-summary")
async def regenerate_daily_summary(
    subject: str = Query(None, description="e.g. Science, Maths, English"),
    chapter_number: int = Query(1, description="Chapter number (only when daily_id absent)"),
    class_no: int = Query(7, description="Class number"),
    section: str = Query("A"),
    daily_id: str | None = Query(None, description="Regenerate for this doc using its own topic"),
    service: DailyClassService = Depends(get_daily_class_service),
    user: CurrentUser = Depends(require_role("teacher", "admin")),
):
    """Regenerate structured summary blocks for a classes_daily document."""
    return await service.regenerate_summary(
        subject=subject, chapter_number=chapter_number,
        class_no=class_no, section=section, daily_id=daily_id)


@router.post("/daily/mindmap")
async def generate_daily_mindmap(
    daily_id: str = Query(..., description="classes_daily document id"),
    force: bool = Query(False, description="Regenerate even if a mind map is cached"),
    service: DailyClassService = Depends(get_daily_class_service),
    user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin")),
):
    """Hierarchical mind-map tree built from the class's summary_blocks (lazy + cached)."""
    return await service.generate_mindmap(daily_id=daily_id, force=force)


@router.post("/daily/{daily_id}/transcript")
async def add_manual_transcript(
    daily_id: str,
    payload: ManualTranscript,
    service: DailyClassService = Depends(get_daily_class_service),
    user: CurrentUser = Depends(require_role("teacher", "admin")),
):
    """Manually stamp a transcript for a daily class (demos without audio)."""
    return await service.add_manual_transcript(daily_id=daily_id, text=payload.text)


@router.post("/daily/transcript-doc")
async def create_daily_transcript_doc(
    req: DailyTranscriptDoc,
    service: DailyClassService = Depends(get_daily_class_service),
    _: bool = Depends(api_key_guard),
):
    """Insert a daily_transcripts doc with the worker's composite string _id."""
    return await service.create_transcript_doc(req)


@router.post("/daily/summarize")
async def daily_summarize(
    req: SummarizeRequest = Body(default=SummarizeRequest()),
    service: DailyClassService = Depends(get_daily_class_service),
    _: bool = Depends(api_key_guard),
):
    """Unified summary entry (transcript_id-driven, or daily_id/explicit fields)."""
    return await service.summarize(req)


@router.post("/daily/generate-widget")
async def generate_tryit_widget(
    subject: str = Query(..., description="e.g. Science, Maths"),
    chapter_number: int = Query(1),
    class_no: int = Query(7),
    section: str = Query("A"),
    service: DailyClassService = Depends(get_daily_class_service),
    user: CurrentUser = Depends(require_role("teacher", "admin")),
):
    """Generate a Try It Yourself widget from curriculum data and stamp into classes_daily."""
    return await service.generate_widget(
        subject=subject, chapter_number=chapter_number, class_no=class_no, section=section)


# ---------- Provider comparison (internal/admin eval) ----------
@router.post("/compare/generate")
async def generate_provider_comparison(
    req: CompareRequest,
    service: DailyClassService = Depends(get_daily_class_service),
    user: CurrentUser = Depends(require_role("admin")),
):
    """Internal eval: generate a summary + story from EACH transcription provider."""
    return await service.generate_comparison(req)


@router.get("/compare")
async def get_provider_comparison(
    daily_id: str | None = None,
    transcript_id: str | None = None,
    service: DailyClassService = Depends(get_daily_class_service),
    user: CurrentUser = Depends(require_role("admin")),
):
    """Return a cached provider comparison by daily_id or transcript_id."""
    return await service.get_comparison(daily_id=daily_id, transcript_id=transcript_id)


# ---------- Comic story ----------
@router.get("/daily/{daily_id}/comic")
async def get_comic_story(
    daily_id: str,
    student_id: str | None = Query(None),
    service: ContentService = Depends(get_content_service),
    user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin")),
):
    """Fetch (or generate and cache) the animated comic story for a daily class."""
    return await service.get_or_create_comic(daily_id=daily_id, student_id=student_id, requester=user)


@router.post("/daily/{daily_id}/comic-progress")
async def update_comic_progress(
    daily_id: str,
    student_id: str = Body(...),
    panels_read: int = Body(...),
    completed: bool = Body(False),
    service: ContentService = Depends(get_content_service),
    user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin")),
):
    """Track a student's reading progress through the animated comic story."""
    return await service.update_comic_progress(
        daily_id=daily_id, student_id=student_id, panels_read=panels_read,
        completed=completed, requester=user)


# ---------- Animated story (5-rule engine) ----------
@router.get("/story")
async def get_existing_story(
    daily_id: str,
    student_id: str,
    service: ContentService = Depends(get_content_service),
    user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin")),
):
    """Check cache for an existing generated story. Returns story or null."""
    return await service.get_story(daily_id=daily_id, student_id=student_id, requester=user)


@router.post("/story/generate")
async def generate_story_endpoint(
    req: StoryRequest,
    service: ContentService = Depends(get_content_service),
    user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin")),
):
    """Generate (or return cached) animated comic story for a daily class."""
    return await service.generate_story(req, requester=user)


# ---------- Guru-Shishya dialogue story ----------
@router.get("/guru-story")
async def get_existing_guru_story(
    daily_id: str,
    student_id: str,
    service: ContentService = Depends(get_content_service),
    user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin")),
):
    """Check cache for an existing generated Guru-Shishya story. Returns story or null."""
    return await service.get_guru(daily_id=daily_id, student_id=student_id, requester=user)


@router.post("/guru-story/generate")
async def generate_guru_story_endpoint(
    req: GuruStoryRequest,
    service: ContentService = Depends(get_content_service),
    user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin")),
):
    """Generate (or return cached) Guru-Shishya dialogue story for a daily class."""
    return await service.generate_guru(req, requester=user)


# ---------- SILF revision story (NCERT-figure-grounded) ----------
@router.get("/silf-story/formats")
async def list_silf_formats(user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin"))):
    """The narrative formats a student can choose from (id + label + description)."""
    return ContentService.list_silf_formats()


@router.get("/silf-story")
async def get_existing_silf_story(
    daily_id: str,
    student_id: str,
    narrative_format: str | None = None,
    service: ContentService = Depends(get_content_service),
    user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin")),
):
    """Check cache for an existing SILF story (optionally for a specific format)."""
    return await service.get_silf(
        daily_id=daily_id, student_id=student_id, narrative_format=narrative_format, requester=user)


@router.post("/silf-story/generate")
async def generate_silf_story_endpoint(
    req: SilfStoryRequest,
    service: ContentService = Depends(get_content_service),
    user: CurrentUser = Depends(require_role("student", "parent", "teacher", "admin")),
):
    """Generate (or return cached) SILF revision story grounded in real NCERT figures."""
    return await service.generate_silf(req, requester=user)
