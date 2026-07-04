from fastapi import APIRouter, Depends, Query, UploadFile, File, Form

from ..services.ncert_service import NcertService, get_ncert_service

# NOTE: NCERT curriculum metadata is public (no auth gate) — the frontend selectors
# fetch it without a token. Content is global (not tenant-scoped).
router = APIRouter(prefix="/ncert", tags=["NCERT"])


@router.get("/subjects")
async def get_subjects(
    class_no: str = Query(..., description="Class number (e.g. '6')"),
    service: NcertService = Depends(get_ncert_service),
):
    """Distinct subjects for a class, merged across ncert_textbooks + curriculum_chapters."""
    return await service.get_subjects(class_no)


@router.get("/chapters")
async def get_chapters(
    class_no: str = Query(..., description="Class number"),
    subject: str = Query(..., description="Subject name"),
    service: NcertService = Depends(get_ncert_service),
):
    """Chapters for a class+subject, merged across collections."""
    return await service.get_chapters(class_no, subject)


@router.get("/topics")
async def get_topics(
    chapter_unique_id: str = Query(..., description="Unique ID of the chapter"),
    service: NcertService = Depends(get_ncert_service),
):
    """Topics for a chapter (explicit topic docs, or curriculum toc/concepts)."""
    return await service.get_topics(chapter_unique_id)


@router.post("/chapter/upload")
async def upload_chapter(
    file: UploadFile = File(..., description="NCERT chapter PDF"),
    class_no: int = Form(...),
    subject: str = Form(...),
    chapter_key: str = Form(..., description="Stable chapter id, e.g. science_class9_ch05"),
    chapter_title: str = Form(""),
    chapter_number: int = Form(0),
    service: NcertService = Depends(get_ncert_service),
):
    """Ingest a chapter PDF (figures + text/tables) and ensure a curriculum row exists."""
    pdf_bytes = await file.read()
    return await service.ingest_chapter(
        pdf_bytes=pdf_bytes, filename=file.filename, class_no=class_no, subject=subject,
        chapter_key=chapter_key, chapter_title=chapter_title, chapter_number=chapter_number)


@router.get("/figures")
async def list_figures(
    chapter_key: str = Query(..., description="Chapter id used at ingestion time"),
    service: NcertService = Depends(get_ncert_service),
):
    """Catalog of figures for a chapter (no image bytes)."""
    return await service.list_figures(chapter_key)


@router.get("/figure/{figure_id}")
async def get_figure(
    figure_id: str,
    service: NcertService = Depends(get_ncert_service),
):
    """Single figure with its base64 image — lazy read path for the story view."""
    return await service.get_figure(figure_id)
