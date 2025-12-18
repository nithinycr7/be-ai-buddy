
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import List, Dict, Any, Optional
from ..db.mongo import get_db
from ..core.config import settings

router = APIRouter(prefix="/ncert", tags=["NCERT"])

@router.get("/subjects")
async def get_subjects(
    class_no: str = Query(..., description="Class number (e.g. '6')"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Get distinct subjects for a specific class.
    Querying ncert_topics collection where doc_type matches 'chapter_metadata' 
    or just by existence of class/subject fields if using flexible schema.
    """
    # Using the collection defined in config
    collection = db[settings.NCERT_COLLECTION_NAME] 
    
    # Efficient distinct query
    subjects = await collection.distinct("subject", {"class_no": class_no})
    return {"subjects": sorted(subjects)}

@router.get("/chapters")
async def get_chapters(
    class_no: str = Query(..., description="Class number"),
    subject: str = Query(..., description="Subject name"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Get list of chapters for a class and subject.
    """
    collection = db[settings.NCERT_COLLECTION_NAME]
    
    cursor = collection.find(
        {
            "class_no": class_no, 
            "subject": subject,
            "doc_type": "chapter_metadata" # Ensure we only get metadata docs
        },
        {"title": 1, "chapter_unique_id": 1, "_id": 0}
    ).sort("title", 1)
    
    chapters = await cursor.to_list(length=None)
    return {"chapters": chapters}

@router.get("/topics")
async def get_topics(
    chapter_unique_id: str = Query(..., description="Unique ID of the chapter"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """
    Get list of topics for a specific chapter.
    """
    collection = db[settings.NCERT_COLLECTION_NAME]
    
    cursor = collection.find(
        {
            "chapter_unique_id": chapter_unique_id,
            "doc_type": "topic"
        },
        {"topic_title": 1, "topic_unique_id": 1, "topic_id": 1, "_id": 0}
    ).sort("topic_id", 1) # Sorting by logical topic ID (e.g. 2.1, 2.2)
    
    topics = await cursor.to_list(length=None)
    return {"topics": topics}
