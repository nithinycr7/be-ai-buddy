"""Repositories for GLOBAL NCERT curriculum content.

INTENTIONALLY NOT tenant-scoped: NCERT curriculum is shared across all tenants and
is keyed by class/subject/chapter, never by tenant. `_scoped` is overridden to a
no-op so these behave as global reads (same rationale as TranscriptRepository).
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from ...core.config import settings
from .base import BaseRepository


# Generous cap for the bounded NCERT-content reads (chapters per class, pages/figures
# per chapter). Callers may pass a smaller limit; nothing is ever read unbounded.
MAX_CONTENT_DOCS = 2000


class _GlobalRepository(BaseRepository):
    def _scoped(self, query: Optional[Mapping[str, Any]] = None) -> dict:
        return dict(query or {})  # no tenant injection — global content


class CurriculumRepository(_GlobalRepository):
    collection = "curriculum_chapters"

    async def find_chapter(self, *, class_no: int, subject: str,
                           chapter_number: Optional[int] = None,
                           projection: Optional[dict] = None) -> Optional[dict]:
        q: dict = {"class": class_no, "subject": {"$regex": f"^{subject}$", "$options": "i"}}
        if chapter_number is not None:
            q["chapter_number"] = chapter_number
        return await self.find_one(q, projection=projection)

    async def get_by_chapter_key(self, chapter_key: str, projection: Optional[dict] = None) -> Optional[dict]:
        return await self.find_one({"chapter_key": chapter_key}, projection=projection)

    async def distinct_subjects(self, class_no: int) -> List[str]:
        return await self.c.distinct("subject", {"class": class_no})

    async def list_chapters(self, *, class_no: int, subject_variants: List[str], limit: int = MAX_CONTENT_DOCS) -> List[dict]:
        cur = self.c.find(
            {"class": class_no, "subject": {"$in": subject_variants}},
            {"chapter_title": 1, "chapter_key": 1, "chapter_number": 1, "_id": 0},
        ).sort("chapter_number", 1)
        return await cur.to_list(length=limit)

    async def ensure_chapter(self, chapter_key: str, doc: dict) -> bool:
        """Insert a curriculum row if none exists for chapter_key. Returns True if created."""
        if await self.find_one({"chapter_key": chapter_key}, projection={"_id": 1}):
            return False
        await self.insert_one(doc)
        return True


class NcertTextbookRepository(_GlobalRepository):
    """Legacy `ncert_textbooks` (chapter_metadata + topic docs), class_no stored as str."""
    collection = settings.NCERT_COLLECTION_NAME

    async def distinct_subjects(self, class_no: str) -> List[str]:
        return await self.c.distinct("subject", {"class_no": class_no})

    async def list_chapters(self, *, class_no: str, subject_variants: List[str], limit: int = MAX_CONTENT_DOCS) -> List[dict]:
        cur = self.c.find(
            {"class_no": class_no, "subject": {"$in": subject_variants}, "doc_type": "chapter_metadata"},
            {"title": 1, "chapter_unique_id": 1, "_id": 0},
        ).sort("title", 1)
        return await cur.to_list(length=limit)

    async def list_topics(self, chapter_unique_id: str, limit: int = MAX_CONTENT_DOCS) -> List[dict]:
        cur = self.c.find(
            {"chapter_unique_id": chapter_unique_id, "doc_type": "topic"},
            {"topic_title": 1, "topic_unique_id": 1, "topic_id": 1, "_id": 0},
        ).sort("topic_id", 1)
        return await cur.to_list(length=limit)


class NcertFigureRepository(_GlobalRepository):
    collection = "ncert_figures"

    async def list_for_chapter(self, chapter_key: str, limit: int = MAX_CONTENT_DOCS) -> List[dict]:
        cur = self.c.find({"chapter_key": chapter_key}, {"image_b64": 0})
        return await cur.to_list(length=limit)

    async def get(self, figure_id: str) -> Optional[dict]:
        return await self.find_one({"_id": figure_id})


class NcertContentRepository(_GlobalRepository):
    """Chapter text pages + figures (both global, keyed by chapter_key)."""
    collection = "ncert_chapter_text"

    async def pages_for_chapter(self, chapter_key: str, limit: int = MAX_CONTENT_DOCS) -> list:
        cur = self.db.ncert_chapter_text.find(
            {"chapter_key": chapter_key}, {"text": 1, "page": 1, "_id": 0}
        ).sort("page", 1)
        return await cur.to_list(length=limit)

    async def figures_for_chapter(self, chapter_key: str, limit: int = MAX_CONTENT_DOCS) -> list:
        cur = self.db.ncert_figures.find(
            {"chapter_key": chapter_key},
            {"_id": 1, "figure_number": 1, "caption": 1},
        )
        return await cur.to_list(length=limit)
