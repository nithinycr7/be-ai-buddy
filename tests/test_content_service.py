"""
ContentService cache/validation/ownership coverage (no LLM calls — exercises the
cache-hit + domain-exception paths of comic/story/guru/silf after the
router→service→repository migration).

    MONGODB_DB=mymedha_repo_test ./venv/bin/python -m tests.test_content_service
"""
import asyncio, os, sys, types
os.environ.setdefault("MONGODB_DB", "mymedha_repo_test")
from bson import ObjectId
from app.db.mongo import get_db
from app.db.repositories import (
    ComicStoryRepository, DailyClassRepository, StudentRepository,
    StudentDailyProgressRepository, StoryGenerationRepository, GuruStoryRepository,
    SilfStoryRepository, TranscriptRepository, CurriculumRepository, NcertContentRepository)
from app.services.content_service import (
    ContentService, StoryRequest, GuruStoryRequest, SilfStoryRequest)
from app.services.silf_story_service import resolve_format
from app.core.exceptions import BadRequestError, NotFoundError, ForbiddenError

T = "T1"; SID = "STU-1"
COLL = ("classes_daily", "comic_stories", "story_generations", "guru_shishya_stories", "silf_story_generations")

def _svc(db, tenant=T):
    return ContentService(
        comic=ComicStoryRepository(db, tenant), daily=DailyClassRepository(db, tenant),
        students=StudentRepository(db, tenant), progress=StudentDailyProgressRepository(db, tenant),
        stories=StoryGenerationRepository(db, tenant), guru=GuruStoryRepository(db, tenant),
        silf=SilfStoryRepository(db, tenant), transcripts=TranscriptRepository(db, tenant),
        curriculum=CurriculumRepository(db, tenant), ncert=NcertContentRepository(db, tenant))

async def main():
    db = await get_db()
    for c in COLL: await db[c].delete_many({})
    doid = ObjectId(); did = str(doid)
    await db.classes_daily.insert_one({"_id": doid, "tenant": T, "topics": ["Filtration"], "subject": "Science", "class_no": 9})
    await db.comic_stories.insert_one({"daily_id": did, "tenant": T, "panels": [1, 2], "topic": "Filtration"})
    await db.story_generations.insert_one({"daily_id": did, "student_id": SID, "tenant": T, "story": "STORY"})
    await db.guru_shishya_stories.insert_one({"daily_id": did, "student_id": SID, "tenant": T, "story": "GURU"})
    fmt = resolve_format("detective", "Science")
    await db.silf_story_generations.insert_one({"daily_id": did, "student_id": SID, "tenant": T, "narrative_format": fmt, "story": "SILF"})

    su = types.SimpleNamespace(role="student", student_id=SID, kids=[])
    ou = types.SimpleNamespace(role="student", student_id="STU-2", kids=[])
    svc = _svc(db); res = []

    c = await svc.get_or_create_comic(daily_id=did, student_id=SID, requester=su)
    res.append(("comic cache hit (no LLM)", c.get("panels") == [1, 2]))
    s = await svc.get_story(daily_id=did, student_id=SID, requester=su)
    res.append(("story get cache hit", s["story"] == "STORY" and s["from_cache"]))
    sg = await svc.generate_story(StoryRequest(daily_id=did, student_id=SID, grade=9), requester=su)
    res.append(("story generate returns cache", sg["from_cache"] and sg["story"] == "STORY"))
    gg = await svc.generate_guru(GuruStoryRequest(daily_id=did, student_id=SID, grade=9), requester=su)
    res.append(("guru generate returns cache", gg["from_cache"] and gg["story"] == "GURU"))
    sf = await svc.generate_silf(SilfStoryRequest(daily_id=did, student_id=SID, grade=9, narrative_format="detective"), requester=su)
    res.append(("silf generate returns cache", sf["from_cache"] and sf["story"] == "SILF"))

    # validation + ownership (domain exceptions)
    try:
        await svc.get_or_create_comic(daily_id="not-an-oid", student_id=SID, requester=su)
        res.append(("invalid daily_id -> BadRequest400", False))
    except BadRequestError as e: res.append(("invalid daily_id -> BadRequest400", e.status_code == 400))
    try:
        await svc.get_story(daily_id=did, student_id=SID, requester=ou)
        res.append(("other student -> Forbidden403", False))
    except ForbiddenError as e: res.append(("other student -> Forbidden403", e.status_code == 403))
    # cross-tenant daily not visible -> generate_story sees no daily -> NotFound
    try:
        await _svc(db, "OTHER").generate_story(StoryRequest(daily_id=did, student_id=SID, grade=9, force=True), requester=su)
        res.append(("cross-tenant daily -> NotFound404", False))
    except NotFoundError as e: res.append(("cross-tenant daily -> NotFound404", e.status_code == 404))

    for c in COLL: await db[c].delete_many({})
    ok = all(p for _, p in res)
    for n, p in res: print(f"  {'PASS' if p else 'FAIL'}  {n}")
    print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
    return ok

sys.exit(0 if asyncio.run(main()) else 1)
