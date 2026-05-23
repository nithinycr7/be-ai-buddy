
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Dict, Any, Optional
from ..db.mongo import get_db
from ..core.config import settings

router = APIRouter(prefix="/ncert", tags=["NCERT"])

CURRICULUM_COLLECTION = "curriculum_chapters"

# Some legacy ncert_textbooks docs use "Social Sciences" (plural).
# curriculum_chapters and the rest of the platform use "Social Science".
# Normalize on output and accept both on input.
SUBJECT_ALIASES = {
    "Social Sciences": "Social Science",
}


def _normalize_subject(s: str) -> str:
    return SUBJECT_ALIASES.get(s, s)


def _denormalize_subject_candidates(s: str) -> List[str]:
    """For an incoming subject, return all DB-stored variants we should match."""
    candidates = {s}
    for db_value, canonical in SUBJECT_ALIASES.items():
        if canonical == s:
            candidates.add(db_value)
    return list(candidates)


@router.get("/subjects")
async def get_subjects(
    class_no: str = Query(..., description="Class number (e.g. '6')"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Distinct subjects for a class, merged across ncert_textbooks (legacy schema, class_no: str)
    and curriculum_chapters (class: int).
    """
    textbooks = db[settings.NCERT_COLLECTION_NAME]
    curriculum = db[CURRICULUM_COLLECTION]

    tb_subjects = await textbooks.distinct("subject", {"class_no": class_no})

    try:
        class_int = int(class_no)
        cc_subjects = await curriculum.distinct("subject", {"class": class_int})
    except (TypeError, ValueError):
        cc_subjects = []

    merged = {_normalize_subject(s) for s in (tb_subjects + cc_subjects) if s}
    return {"subjects": sorted(merged)}


@router.get("/chapters")
async def get_chapters(
    class_no: str = Query(..., description="Class number"),
    subject: str = Query(..., description="Subject name"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Chapters for a class+subject, merged across collections.
    curriculum_chapters docs surface chapter_key as chapter_unique_id so the
    topics endpoint can resolve them.
    """
    textbooks = db[settings.NCERT_COLLECTION_NAME]
    curriculum = db[CURRICULUM_COLLECTION]

    subject_variants = _denormalize_subject_candidates(subject)

    tb_cursor = textbooks.find(
        {
            "class_no": class_no,
            "subject": {"$in": subject_variants},
            "doc_type": "chapter_metadata",
        },
        {"title": 1, "chapter_unique_id": 1, "_id": 0},
    ).sort("title", 1)
    tb_chapters = await tb_cursor.to_list(length=None)

    try:
        class_int = int(class_no)
        cc_cursor = curriculum.find(
            {"class": class_int, "subject": {"$in": subject_variants}},
            {
                "chapter_title": 1,
                "chapter_key": 1,
                "chapter_number": 1,
                "_id": 0,
            },
        ).sort("chapter_number", 1)
        cc_docs = await cc_cursor.to_list(length=None)
    except (TypeError, ValueError):
        cc_docs = []

    cc_chapters = [
        {
            "chapter_unique_id": d["chapter_key"],
            "title": d.get("chapter_title", ""),
        }
        for d in cc_docs
        if d.get("chapter_key")
    ]

    seen_ids = set()
    merged: List[Dict[str, Any]] = []
    for ch in tb_chapters + cc_chapters:
        cid = ch.get("chapter_unique_id")
        if not cid or cid in seen_ids:
            continue
        seen_ids.add(cid)
        merged.append(ch)

    return {"chapters": merged}


@router.get("/topics")
async def get_topics(
    chapter_unique_id: str = Query(..., description="Unique ID of the chapter"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Topics for a chapter. ncert_textbooks chapters have explicit topic docs;
    curriculum_chapters chapters expose their `concepts` array mapped to topics.
    """
    textbooks = db[settings.NCERT_COLLECTION_NAME]
    curriculum = db[CURRICULUM_COLLECTION]

    cursor = textbooks.find(
        {"chapter_unique_id": chapter_unique_id, "doc_type": "topic"},
        {"topic_title": 1, "topic_unique_id": 1, "topic_id": 1, "_id": 0},
    ).sort("topic_id", 1)
    topics = await cursor.to_list(length=None)
    if topics:
        return {"topics": topics}

    cc_doc = await curriculum.find_one(
        {"chapter_key": chapter_unique_id},
        {"concepts": 1, "chapter_number": 1, "_id": 0},
    )
    if not cc_doc:
        return {"topics": []}

    chapter_no = cc_doc.get("chapter_number", 0)
    derived: List[Dict[str, Any]] = []
    for idx, concept in enumerate(cc_doc.get("concepts", []) or [], start=1):
        title = (concept or {}).get("name") or (concept or {}).get("concept_id")
        if not title:
            continue
        cid = (concept or {}).get("concept_id") or f"{chapter_no}.{idx}"
        derived.append(
            {
                "topic_title": title,
                "topic_id": f"{chapter_no}.{idx}",
                "topic_unique_id": f"{chapter_unique_id}::{cid}",
            }
        )

    return {"topics": derived}
