"""
NCERT curriculum-metadata business logic (global, un-tenanted content).
router → NcertService → global repositories.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends

from ..core.exceptions import AppError, BadRequestError, NotFoundError
from ..db.repositories import (
    CurriculumRepository, get_curriculum_repo,
    NcertFigureRepository, get_ncert_figure_repo,
    NcertTextbookRepository, get_ncert_textbook_repo,
)

# Some legacy ncert_textbooks docs use "Social Sciences" (plural); the rest of the
# platform uses "Social Science". Normalize on output, accept both on input.
SUBJECT_ALIASES = {"Social Sciences": "Social Science"}


def _normalize_subject(s: str) -> str:
    return SUBJECT_ALIASES.get(s, s)


def _subject_variants(s: str) -> List[str]:
    variants = {s}
    for db_value, canonical in SUBJECT_ALIASES.items():
        if canonical == s:
            variants.add(db_value)
    return list(variants)


class NcertService:
    def __init__(self, textbooks: NcertTextbookRepository, curriculum: CurriculumRepository,
                 figures: NcertFigureRepository):
        self.textbooks = textbooks
        self.curriculum = curriculum
        self.figures = figures

    async def get_subjects(self, class_no: str) -> dict:
        tb_subjects = await self.textbooks.distinct_subjects(class_no)
        try:
            cc_subjects = await self.curriculum.distinct_subjects(int(class_no))
        except (TypeError, ValueError):
            cc_subjects = []
        merged = {_normalize_subject(s) for s in (tb_subjects + cc_subjects) if s}
        return {"subjects": sorted(merged)}

    async def get_chapters(self, class_no: str, subject: str) -> dict:
        variants = _subject_variants(subject)
        tb_chapters = await self.textbooks.list_chapters(class_no=class_no, subject_variants=variants)
        try:
            cc_docs = await self.curriculum.list_chapters(class_no=int(class_no), subject_variants=variants)
        except (TypeError, ValueError):
            cc_docs = []
        cc_chapters = [
            {"chapter_unique_id": d["chapter_key"], "title": d.get("chapter_title", "")}
            for d in cc_docs if d.get("chapter_key")
        ]
        seen, merged = set(), []
        for ch in tb_chapters + cc_chapters:
            cid = ch.get("chapter_unique_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            merged.append(ch)
        return {"chapters": merged}

    async def get_topics(self, chapter_unique_id: str) -> dict:
        topics = await self.textbooks.list_topics(chapter_unique_id)
        if topics:
            return {"topics": topics}

        cc_doc = await self.curriculum.get_by_chapter_key(
            chapter_unique_id, projection={"concepts": 1, "chapter_number": 1, "toc": 1, "_id": 0})
        if not cc_doc:
            return {"topics": []}

        toc = cc_doc.get("toc")
        if toc:
            return {"topics": [
                {
                    "topic_title": f"{t['number']} {t['name']}",
                    "topic_id": t["number"],
                    "topic_unique_id": t["topic_id"],
                    "subtopics": [
                        {"topic_title": f"{s['number']} {s['name']}", "topic_unique_id": s["subtopic_id"]}
                        for s in t.get("subtopics", [])
                    ],
                }
                for t in toc
            ]}

        chapter_no = cc_doc.get("chapter_number", 0)
        derived: List[Dict[str, Any]] = []
        for idx, concept in enumerate(cc_doc.get("concepts", []) or [], start=1):
            title = (concept or {}).get("name") or (concept or {}).get("concept_id")
            if not title:
                continue
            cid = (concept or {}).get("concept_id") or f"{chapter_no}.{idx}"
            derived.append({
                "topic_title": title,
                "topic_id": f"{chapter_no}.{idx}",
                "topic_unique_id": f"{chapter_unique_id}::{cid}",
            })
        return {"topics": derived}

    async def ingest_chapter(self, *, pdf_bytes: bytes, filename: Optional[str], class_no: int,
                             subject: str, chapter_key: str, chapter_title: str,
                             chapter_number: int) -> dict:
        if not (filename or "").lower().endswith(".pdf"):
            raise BadRequestError("Please upload a PDF file")
        if not pdf_bytes:
            raise BadRequestError("Empty file")

        from app.services.ncert_ingest_service import ingest_chapter_pdf
        norm_subject = _normalize_subject(subject)
        try:
            result = await ingest_chapter_pdf(
                pdf_bytes=pdf_bytes, chapter_key=chapter_key, class_no=class_no,
                subject=norm_subject, source_name=filename or "uploaded.pdf")
        except Exception as e:
            raise AppError(f"Ingestion failed: {e}")

        # Ensure a curriculum_chapters row exists so story endpoints can resolve chapter_key.
        now = datetime.now(timezone.utc)
        await self.curriculum.ensure_chapter(chapter_key, {
            "chapter_key": chapter_key, "board": "NCERT", "class": class_no,
            "subject": norm_subject, "chapter_number": chapter_number or 0,
            "chapter_title": chapter_title or chapter_key, "concepts": [],
            "created_at": now, "updated_at": now, "source": "ncert_chapter_upload"})
        return result

    async def list_figures(self, chapter_key: str) -> dict:
        figs = await self.figures.list_for_chapter(chapter_key)
        figs.sort(key=lambda f: [int(x) for x in str(f.get("figure_number", "0")).split(".") if x.isdigit()] or [0])
        return {"figures": figs}

    async def get_figure(self, figure_id: str) -> dict:
        doc = await self.figures.get(figure_id)
        if not doc:
            raise NotFoundError("Figure not found")
        return {
            "figure_id": doc["_id"], "figure_number": doc.get("figure_number"),
            "caption": doc.get("caption"), "image_b64": doc.get("image_b64"),
            "width": doc.get("width"), "height": doc.get("height"),
        }


def get_ncert_service(
    textbooks: NcertTextbookRepository = Depends(get_ncert_textbook_repo),
    curriculum: CurriculumRepository = Depends(get_curriculum_repo),
    figures: NcertFigureRepository = Depends(get_ncert_figure_repo),
) -> NcertService:
    return NcertService(textbooks, curriculum, figures)
