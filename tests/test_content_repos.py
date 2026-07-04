"""
Tests for the generated-content repositories used by classes.py (story / guru /
silf / comic) + the global curriculum repo.

Headline guarantee: the story/guru/silf caches used to be READ with a tenant
filter but WRITTEN via replace_one filters that omitted tenant. These repos scope
the write filter too, so two tenants sharing a (daily_id, student_id) no longer
overwrite each other. Also checks the silf per-format cache and that curriculum
is global (not tenant-scoped).

Requires a Mongo connection; uses a throwaway DB:
    MONGODB_DB=mymedha_repo_test ./venv/bin/python -m tests.test_content_repos
Exits non-zero on any failure.
"""
import asyncio
import os
import sys

os.environ.setdefault("MONGODB_DB", "mymedha_repo_test")

from app.db.mongo import get_db  # noqa: E402
from app.db.repositories import (  # noqa: E402
    ComicStoryRepository, CurriculumRepository, SilfStoryRepository,
    StoryGenerationRepository,
)

COLLECTIONS = ("story_generations", "silf_story_generations", "comic_stories", "curriculum_chapters")


async def _run():
    db = await get_db()
    for c in COLLECTIONS:
        await db[c].delete_many({})

    a_story, b_story = StoryGenerationRepository(db, "A"), StoryGenerationRepository(db, "B")
    checks = []

    # upsert scopes tenant on BOTH filter and doc (closes the write-gap)
    await a_story.upsert(daily_id="D1", student_id="S1", doc={"daily_id": "D1", "student_id": "S1", "story": "tenantA"})
    got = await a_story.get(daily_id="D1", student_id="S1")
    checks.append(("story stored with tenant A", bool(got) and got.get("tenant") == "A"))
    checks.append(("tenant B cannot read A's story", await b_story.get(daily_id="D1", student_id="S1") is None))

    # B writes same (daily, student): a SEPARATE row, must not overwrite A
    await b_story.upsert(daily_id="D1", student_id="S1", doc={"daily_id": "D1", "student_id": "S1", "story": "tenantB"})
    checks.append(("A's story intact after B writes",
                   (await a_story.get(daily_id="D1", student_id="S1"))["story"] == "tenantA"))
    checks.append(("two tenant rows exist", await db.story_generations.count_documents({"daily_id": "D1"}) == 2))

    # idempotent: A upserts again -> still one A row
    await a_story.upsert(daily_id="D1", student_id="S1", doc={"daily_id": "D1", "student_id": "S1", "story": "tenantA2"})
    checks.append(("A upsert idempotent (1 A row)",
                   await db.story_generations.count_documents({"daily_id": "D1", "tenant": "A"}) == 1))

    # silf: per-(daily, student, format) cache
    silf = SilfStoryRepository(db, "A")
    await silf.upsert(daily_id="D1", student_id="S1", narrative_format="comic",
                      doc={"daily_id": "D1", "student_id": "S1", "narrative_format": "comic", "story": "c"})
    await silf.upsert(daily_id="D1", student_id="S1", narrative_format="diary",
                      doc={"daily_id": "D1", "student_id": "S1", "narrative_format": "diary", "story": "d"})
    checks.append(("silf per-format rows == 2", await db.silf_story_generations.count_documents({"daily_id": "D1"}) == 2))
    checks.append(("silf get by format", (await silf.get(daily_id="D1", student_id="S1", narrative_format="diary"))["story"] == "d"))

    # comic: projection + tenant isolation
    comic = ComicStoryRepository(db, "A")
    await comic.create({"daily_id": "D1", "panels": [1, 2, 3], "completion_xp": 70})
    cp = await comic.get_by_daily("D1", projection={"panels": 1, "completion_xp": 1})
    checks.append(("comic projection returns panels", bool(cp) and len(cp.get("panels", [])) == 3 and cp.get("completion_xp") == 70))
    checks.append(("comic tenant-isolated", await ComicStoryRepository(db, "B").get_by_daily("D1") is None))

    # curriculum: global (not tenant-scoped) + case-insensitive subject
    await db.curriculum_chapters.insert_one({"class": 9, "subject": "Science", "chapter_key": "sci9c1", "chapter_number": 1})
    ch = await CurriculumRepository(db, "ANY").find_chapter(class_no=9, subject="science")
    checks.append(("curriculum global + case-insensitive", bool(ch) and ch.get("chapter_key") == "sci9c1"))

    for c in COLLECTIONS:
        await db[c].delete_many({})

    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    passed = all(ok for _, ok in checks)
    print("\nRESULT:", "ALL PASS" if passed else "FAILURES")
    return passed


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(_run()) else 1)
