import logging
from typing import Optional, List, Dict
from datetime import datetime
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings
from app.services.ai import get_client

# Configure logger
logger = logging.getLogger(__name__)

class SummaryService:
    def __init__(self, db_client: AsyncIOMotorClient):
        # We use the same client but connect to specific databases
        # Standard backend DB:
        self.db: AsyncIOMotorDatabase = db_client[settings.MONGODB_DB]
        # Transcripts DB (same URI, different DB name):
        self.transcripts_db: AsyncIOMotorDatabase = db_client["mymedha_dev"]
        
        self.ncert_collection = self.db[settings.NCERT_COLLECTION_NAME]
        self.summary_collection = self.db.student_daily_summary
        
    async def generate_summary(self, transcript_id: str) -> bool:
        """
        Main entry point:
        1. Fetch trigger transcript metadata
        2. Aggregate all related transcripts (Day + Class + Subject + Topic)
        3. Fetch NCERT context
        4. Generate Summary via LLM
        5. Save result
        """
        try:
            # 1. Fetch Trigger Transcript
            trigger_doc = await self.transcripts_db.daily_transcripts.find_one({"_id": transcript_id})
            if not trigger_doc:
                logger.error(f"Transcript not found: {transcript_id}")
                return False

            # Extract Metadata
            school_id = trigger_doc.get("schoolId") # schoolId in worker.py
            class_id = trigger_doc.get("classId")
            subject = trigger_doc.get("subject")
            timestamp = trigger_doc.get("timestamp")
            
            # Identify Date (from timestamp)
            dt = datetime.fromtimestamp(timestamp)
            start_of_day = int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            end_of_day = int(dt.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp())

            # 2. Key Step: Topic Identification (from Trigger Transcript)
            # We need a robust way to know the "Topic". 
            # Ideally, the worker or previous step identified it. 
            # If not, we might need a quick LLM call here to extract "NCERT Topic" from text.
            # For now, let's assume the transcription worker or metadata contains it, 
            # OR we infer it from the aggregated text.
            # Let's try to aggregate first by Class+Subject+Date.
            
            cursor = self.transcripts_db.daily_transcripts.find({
                "schoolId": school_id,
                "classId": class_id,
                "subject": subject,
                "timestamp": {"$gte": start_of_day, "$lte": end_of_day}
            })
            
            related_docs = await cursor.to_list(length=None)
            if not related_docs:
                logger.warning("No related transcripts found (consistency check failed?)")
                return False
                
            combined_text = "\n\n".join([doc.get("transcript_text", "") for doc in related_docs])
            
            # Identify Topic from Combined Text using LLM
            topic_info = await self._identify_topic(combined_text, class_id, subject)
            chapter_name = topic_info.get("chapter")
            topic_name = topic_info.get("topic")
            
            if not chapter_name or not topic_name:
                logger.error(f"Could not identify topic for {subject} class {class_id}")
                return False

            # 3. Fetch NCERT Data
            ncert_context = await self._fetch_ncert_context(class_id, subject, chapter_name, topic_name)
            
            # 4. Generate Summary
            summary_result = await self._generate_llm_summary(combined_text, ncert_context)
            
            # 5. Save Summary
            summary_doc = {
                "school_id": school_id,
                "class_id": class_id,
                "section": "A", # TODO: Where to get section? Assumed 'A' or need to extract from daily_id parsing logic if encoded
                "subject": subject,
                "date": dt.date().isoformat(),
                "chapter": chapter_name,
                "topic": topic_name,
                "summary": summary_result,
                "transcript_ids": [str(d["_id"]) for d in related_docs],
                "created_at": datetime.utcnow().isoformat()
            }
            
            # Upsert ID based on core fields to avoid duplicates for same day/class/subject
            composite_id = f"{school_id}_{class_id}_{subject}_{dt.date().isoformat()}"
            await self.summary_collection.update_one(
                {"_id": composite_id},
                {"$set": summary_doc},
                upsert=True
            )
            
            logger.info(f"✅ Generated Summary for {composite_id}")
            return True

        except Exception as e:
            logger.error(f"Summary Generation Failed: {e}", exc_info=True)
            return False

    async def _identify_topic(self, text: str, class_id: str, subject: str) -> Dict[str, str]:
        """
        Ask LLM to identify the most likely NCERT Chapter and Topic from the transcript.
        """
        client = get_client()
        prompt = f"""
        Analyze this classroom transcript for Class {class_id} {subject}.
        Identify the matching NCERT Chapter and Topic.
        
        Transcript Snippet:
        {text[:2000]}... (truncated)

        Return JSON:
        {{
            "chapter": "Exact Chapter Name",
            "topic": "Exact Topic Name"
        }}
        """
        
        try:
            resp = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": "You are an automated curriculum mapper. Return strictly JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )
            import json
            return json.loads(resp.choices[0].message.content)
        except Exception:
            return {"chapter": None, "topic": None}

    async def _fetch_ncert_context(self, class_id: str, subject: str, chapter: str, topic: str) -> str:
        """
        Fetch structured data from NCERT collection.
        """
        # Flexible match for chapter name (case insensitive regex)
        import re
        # Pattern to match chapter name roughly
        # This might need vector search in future for robustness
        doc = await self.ncert_collection.find_one({
            "class_no": str(class_id), # Ensure string/int consistency
            "subject": subject,
            "chapter": {"$regex": f"^{re.escape(chapter)}", "$options": "i"}
        })
        
        if not doc:
            return "No specific NCERT data found."
            
        # Build Context String
        context = f"Chapter: {doc.get('chapter')}\n"
        context += f"Chapter Summary: {doc.get('chapter_summary', '')}\n"
        
        # Find specific topic
        target_topic = None
        for t in doc.get("topics", []):
            if topic.lower() in t.get("name", "").lower():
                target_topic = t
                break
        
        if target_topic:
            context += f"Topic: {target_topic.get('name')}\n"
            context += f"Topic Summary: {target_topic.get('summary')}\n"
            context += f"Activities: {', '.join(target_topic.get('activities', []))}\n"
        
        return context

    async def _generate_llm_summary(self, transcript: str, context: str) -> str:
        client = get_client()

        system_prompt = """You are an expert teacher's assistant creating visual, structured class summaries for students aged 8-15.

STRICT RULES:
- Use ONLY facts from the provided transcript and NCERT context. Do NOT add external information.
- Use language appropriate for the student's class level.
- ALWAYS include at least one Mermaid diagram — this is MANDATORY.

OUTPUT FORMAT (Markdown):

## 📌 Key Concept
One-line summary of what was taught today.

## 🔑 Key Terms
| Term | Meaning |
|------|---------|
| ... | ... |

## 📖 What We Learned
2-4 short paragraphs explaining the topic simply. Use bullet points where helpful.

## 📊 Diagram
A Mermaid diagram that visually explains the concept. Wrap in ```mermaid code block.

Choose the BEST diagram type for the subject:
- Science (biology/chemistry): flowchart showing processes (e.g., photosynthesis flow, chemical reactions)
- Science (physics): flowchart showing cause-effect or force diagrams
- Math: flowchart showing step-by-step problem solving approach or concept relationships
- History/Social Studies: timeline using graph LR with dates and events
- Geography: flowchart showing relationships (e.g., climate → vegetation → wildlife)
- English/Language: flowchart showing grammar rules or story structure
- General: mindmap or flowchart showing concept hierarchy

DIAGRAM RULES:
- Use graph TD (top-down) for processes, graph LR (left-right) for timelines
- Keep max 8-10 nodes so it stays readable
- Use DESCRIPTIVE labels (e.g. "Sunlight provides energy" NOT just "Sunlight")
- Use subgraphs to group related concepts with clear titles
- Add emojis in labels for visual appeal (e.g. "🌞 Sunlight" → "🌿 Leaf")
- Connect nodes with labeled arrows explaining the relationship (e.g. -->|absorbs|)

## 💡 Remember This
One memorable analogy or memory trick that connects to real life."""

        user_prompt = f"""# NCERT Framework
{context}

# Classroom Transcript
{transcript}

Generate the structured visual summary following the exact format specified."""

        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5
        )
        return resp.choices[0].message.content
