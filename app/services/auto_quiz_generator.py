"""
Auto Quiz Generator Service
Generates daily quizzes from transcripts with fallback logic
"""

from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime
from typing import Dict, Any, List, Optional
from app.services.ai import extract_transcript_metadata, generate_daily_quiz, generate_revision_quiz
from app.models.schemas import Quiz, QuizQuestion, QuizOption


# TODO: Connect to mymedha_db to fetch actual transcripts
# Multi-school support: Fetch transcript by:
#   - school_id (tenant) - REQUIRED for multi-tenancy
#   - class_no
#   - section
#   - subject
#   - chapter (optional)
#   - topic (optional)
# For now, using static transcript
STATIC_TRANSCRIPT = """
Today we learned about photosynthesis, the process by which plants make their own food. 
Plants use sunlight, water, and carbon dioxide to produce glucose and oxygen. 
The green pigment chlorophyll in the leaves captures sunlight energy. 
This process happens in the chloroplasts of plant cells.
The equation for photosynthesis is: 6CO2 + 6H2O + light energy → C6H12O6 + 6O2.
Photosynthesis is essential for life on Earth because it produces oxygen that we breathe.
Plants are called producers because they make their own food through photosynthesis.
"""


async def fetch_transcript_from_mymedha_db(
    mymedha_db,
    school_id: str,
    class_no: int,
    section: str,
    subject: str,
    chapter: Optional[str] = None,
    topic: Optional[str] = None
) -> Optional[str]:
    """
    Helper function to fetch transcript from mymedha_db
    
    Args:
        mymedha_db: MongoDB database connection to mymedha_db
        school_id: School/tenant ID (REQUIRED for multi-school support)
        class_no: Class number (e.g., 7, 8, 9)
        section: Section (e.g., "A", "B")
        subject: Subject name (e.g., "Science", "Math")
        chapter: Optional chapter name
        topic: Optional topic name
        
    Returns:
        Transcript text or None if not found
    """
    # Build query with required fields
    query = {
        "school_id": school_id,
        "class_no": class_no,
        "section": section,
        "subject": subject
    }
    
    # Add optional filters
    if chapter:
        query["chapter"] = chapter
    if topic:
        query["topic"] = topic
    
    # Fetch transcript
    transcript_doc = await mymedha_db.transcripts.find_one(query)
    
    if transcript_doc:
        return transcript_doc.get("text", "")
    
    return None


class AutoQuizGenerator:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.min_confidence_threshold = 0.5
    
    async def generate_quiz_for_daily_class(
        self, 
        daily_id: str,
        tenant: str,
        force_regenerate: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Generate quiz for a specific daily class
        
        Args:
            daily_id: ID of the daily class
            tenant: Tenant/school ID
            force_regenerate: If True, regenerate even if quiz exists
            
        Returns:
            Generated quiz dict or None if failed
        """
        
        from bson import ObjectId
        
        try:
            daily_oid = ObjectId(daily_id)
        except:
             print(f"Invalid daily_id format: {daily_id}")
             return None

        # 1. Check if quiz already exists
        if not force_regenerate:
            existing_quiz = await self.db.quizzes.find_one({
                "daily_id": daily_oid,
                "tenant": tenant
            })
            if existing_quiz:
                print(f"Quiz already exists for daily_id: {daily_id}")
                return existing_quiz
        
        # 2. Get daily class info
        from bson import ObjectId
        daily_class = await self.db.classes_daily.find_one({"_id": ObjectId(daily_id)})
        if not daily_class:
            print(f"Daily class not found: {daily_id}")
            return None
        
        class_no = daily_class.get("class_no")
        section = daily_class.get("section")
        subject = daily_class.get("subject")
        
        
        # 3. Get transcript from mymedha_db
        # TODO: Implement cross-DB connection to mymedha_db
        # Query should filter by:
        #   - school_id: tenant (REQUIRED for multi-school support)
        #   - class_no: class_no
        #   - section: section
        #   - subject: subject
        #   - chapter/topic: daily_class.get("topics") or metadata
        # 
        # Example usage once mymedha_db connection is available:
        # from app.db.mongo import get_mymedha_db
        # mymedha_db = await get_mymedha_db()
        # chapter = daily_class.get("topics", [None])[0] if daily_class.get("topics") else None
        # transcript = await fetch_transcript_from_mymedha_db(
        #     mymedha_db=mymedha_db,
        #     school_id=tenant,
        #     class_no=class_no,
        #     section=section,
        #     subject=subject,
        #     chapter=chapter
        # )
        
        # For now, use static transcript
        transcript = STATIC_TRANSCRIPT
        
        if not transcript or len(transcript) < 50:
            print("Transcript too short or missing, using revision quiz")
            return await self._generate_revision_quiz_for_class(
                daily_id, tenant, class_no, section, subject
            )
        
        # 4. Extract metadata
        metadata = await extract_transcript_metadata(transcript, class_no, subject)
        confidence = metadata.get("confidence", 0.0)
        
        print(f"Transcript metadata: {metadata}")
        
        # 5. Check confidence and generate quiz
        if confidence < self.min_confidence_threshold:
            print(f"Low confidence ({confidence}), using revision quiz")
            return await self._generate_revision_quiz_for_class(
                daily_id, tenant, class_no, section, subject
            )
        
        # 6. Generate daily quiz
        questions_data = await generate_daily_quiz(
            transcript, metadata, class_no, subject
        )
        
        if not questions_data or len(questions_data) == 0:
            print("Failed to generate questions")
            return None
        
        # 7. Create quiz document
        quiz_doc = {
            "daily_id": daily_oid,
            "subject": subject,
            "topic": metadata.get("topic", subject),
            "class_no": class_no,
            "section": section,
            "tenant": tenant,
            "questions": questions_data,
            "auto_generated": True,
            "transcript_id": None,  # TODO: Add when connecting to mymedha_db
            "generation_confidence": confidence,
            "teacher_edited": False,
            "teacher_approved": False,
            "published": True,
            "keywords": metadata.get("keywords", []),
            "difficulty_level": metadata.get("difficulty_level", "medium"),
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        
        # 8. Insert into database
        result = await self.db.quizzes.insert_one(quiz_doc)
        quiz_doc["_id"] = str(result.inserted_id)
        
        print(f"✅ Generated quiz {quiz_doc['_id']} for daily_id: {daily_id}")
        return quiz_doc
    
    async def _generate_revision_quiz_for_class(
        self,
        daily_id: str,
        tenant: str,
        class_no: int,
        section: str,
        subject: str
    ) -> Optional[Dict[str, Any]]:
        """
        Generate revision quiz as fallback
        """
        # Get last 3 topics from previous classes
        cursor = self.db.classes_daily.find({
            "tenant": tenant,
            "class_no": class_no,
            "section": section,
            "subject": subject
        }).sort("date", -1).limit(5)
        
        last_topics = []
        async for doc in cursor:
            topics = doc.get("topics", [])
            last_topics.extend(topics)
        
        last_topics = list(set(last_topics))[:3]  # Unique, max 3
        
        # Generate revision quiz
        questions_data = await generate_revision_quiz(subject, class_no, last_topics)
        
        if not questions_data:
            print("Failed to generate revision quiz")
            return None
        
        # Create quiz document
        
        from bson import ObjectId
        daily_oid = ObjectId(daily_id) if isinstance(daily_id, str) else daily_id
        
        quiz_doc = {
            "daily_id": daily_oid,
            "subject": subject,
            "topic": f"{subject} Revision",
            "class_no": class_no,
            "section": section,
            "tenant": tenant,
            "questions": questions_data,
            "auto_generated": True,
            "transcript_id": None,
            "generation_confidence": 0.3,  # Low confidence for revision
            "teacher_edited": False,
            "teacher_approved": False,
            "published": True,
            "keywords": last_topics,
            "difficulty_level": "medium",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        
        result = await self.db.quizzes.insert_one(quiz_doc)
        quiz_doc["_id"] = str(result.inserted_id)
        
        print(f"✅ Generated revision quiz {quiz_doc['_id']} for daily_id: {daily_id}")
        return quiz_doc
