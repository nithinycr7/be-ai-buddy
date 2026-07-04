"""Repositories for generated learning content (summaries + story variants).

All tenant-scoped. Note these close a defense-in-depth gap in the old classes.py:
the story/guru/silf caches were read with a tenant filter but *written* via
replace_one filters that omitted tenant (the doc body set it, and daily_id is a
globally-unique ObjectId so it wasn't an active leak). Routing writes through
`upsert()` here scopes the filter too, so read and write agree on tenant.
"""
from __future__ import annotations

from typing import Optional

from .base import BaseRepository


class SummaryRepository(BaseRepository):
    collection = "summaries"

    async def create(self, doc: dict):
        return await self.insert_one(doc)


class ComicStoryRepository(BaseRepository):
    collection = "comic_stories"

    async def get_by_daily(self, daily_id: str, projection: Optional[dict] = None) -> Optional[dict]:
        return await self.find_one({"daily_id": daily_id}, projection=projection)

    async def create(self, doc: dict):
        return await self.insert_one(doc)


class StoryGenerationRepository(BaseRepository):
    collection = "story_generations"

    async def get(self, *, daily_id: str, student_id: str, projection: Optional[dict] = None) -> Optional[dict]:
        return await self.find_one(
            {"daily_id": daily_id, "student_id": student_id}, projection=projection
        )

    async def upsert(self, *, daily_id: str, student_id: str, doc: dict):
        # replace_one on the scoped filter (tenant injected by _scoped)
        return await self.c.replace_one(
            self._scoped({"daily_id": daily_id, "student_id": student_id}),
            {**doc, "tenant": self.tenant},
            upsert=True,
        )


class GuruStoryRepository(BaseRepository):
    collection = "guru_shishya_stories"

    async def get(self, *, daily_id: str, student_id: str, projection: Optional[dict] = None) -> Optional[dict]:
        return await self.find_one(
            {"daily_id": daily_id, "student_id": student_id}, projection=projection
        )

    async def upsert(self, *, daily_id: str, student_id: str, doc: dict):
        return await self.c.replace_one(
            self._scoped({"daily_id": daily_id, "student_id": student_id}),
            {**doc, "tenant": self.tenant},
            upsert=True,
        )


class SilfStoryRepository(BaseRepository):
    collection = "silf_story_generations"

    async def get(self, *, daily_id: str, student_id: str,
                  narrative_format: Optional[str] = None,
                  projection: Optional[dict] = None) -> Optional[dict]:
        q = {"daily_id": daily_id, "student_id": student_id}
        if narrative_format:
            q["narrative_format"] = narrative_format
        return await self.find_one(q, projection=projection)

    async def upsert(self, *, daily_id: str, student_id: str, narrative_format: str, doc: dict):
        return await self.c.replace_one(
            self._scoped({
                "daily_id": daily_id, "student_id": student_id,
                "narrative_format": narrative_format,
            }),
            {**doc, "tenant": self.tenant},
            upsert=True,
        )
