"""Repositories for GLOBAL NCERT curriculum content.

INTENTIONALLY NOT tenant-scoped: NCERT curriculum is shared across all tenants and
is keyed by class/subject/chapter, never by tenant. `_scoped` is overridden to a
no-op so these behave as global reads (same rationale as TranscriptRepository).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from .base import BaseRepository


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


class NcertContentRepository(_GlobalRepository):
    """Chapter text pages + figures (both global, keyed by chapter_key)."""
    collection = "ncert_chapter_text"

    async def pages_for_chapter(self, chapter_key: str) -> list:
        cur = self.db.ncert_chapter_text.find(
            {"chapter_key": chapter_key}, {"text": 1, "page": 1, "_id": 0}
        ).sort("page", 1)
        return await cur.to_list(length=None)

    async def figures_for_chapter(self, chapter_key: str) -> list:
        cur = self.db.ncert_figures.find(
            {"chapter_key": chapter_key},
            {"_id": 1, "figure_number": 1, "caption": 1},
        )
        return await cur.to_list(length=None)
