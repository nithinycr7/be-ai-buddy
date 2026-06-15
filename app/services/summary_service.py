import logging
import re
from typing import Optional, List, Dict
from datetime import datetime
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings
from app.services.ai import get_client, get_chat_client

# Configure logger
logger = logging.getLogger(__name__)


def _parse_class_id(class_id) -> tuple[int, str]:
    """'9A' → (9, 'A'); '9' → (9, 'A'); falls back to (9, 'A')."""
    m = re.match(r"\s*(\d+)\s*([A-Za-z]?)", str(class_id or ""))
    if not m:
        return 9, "A"
    return int(m.group(1)), (m.group(2) or "A").upper()

class SummaryService:
    def __init__(self, db_client: AsyncIOMotorClient):
        # We use the same client but connect to specific databases
        # Standard backend DB:
        self.db: AsyncIOMotorDatabase = db_client[settings.MONGODB_DB]
        # Transcripts DB (same URI, different DB name):
        self.transcripts_db: AsyncIOMotorDatabase = db_client["mymedha_dev"]
        
        self.ncert_collection = self.db[settings.NCERT_COLLECTION_NAME]
        self.summary_collection = self.db.student_daily_summary
        
    async def generate_summary(self, transcript_id: str, force: bool = False):
        """
        Entry point driven ONLY by a daily_transcripts._id. Everything else
        (class, section, subject, date, topic, transcript) is derived from the
        transcript collection — used by both the queue worker and the manual API.

        1. Fetch trigger transcript metadata (class / subject / date)
        2. Aggregate the day's related transcripts
        3. Identify the topic from the transcript
        4. Ensure classes_daily + generate approved summary_blocks (transcript-grounded)

        Returns the summary report dict on success, or False on failure.
        """
        try:
            # 1. Fetch Trigger Transcript
            # _id may be a string (worker convention) OR an ObjectId (manually-inserted
            # docs). Try string first, then ObjectId.
            trigger_doc = await self.transcripts_db.daily_transcripts.find_one({"_id": transcript_id})
            if not trigger_doc and ObjectId.is_valid(transcript_id):
                trigger_doc = await self.transcripts_db.daily_transcripts.find_one({"_id": ObjectId(transcript_id)})
                if trigger_doc:
                    logger.warning(
                        f"daily_transcripts[{transcript_id}] uses a non-standard ObjectId _id. "
                        f"The canonical _id is '{{schoolId}}_{{classId}}_{{subject}}_{{timestamp}}' "
                        f"(use POST /api/classes/daily/transcript-doc to insert correctly)."
                    )
            if not trigger_doc:
                logger.error(f"Transcript not found: {transcript_id}")
                return False

            # Extract Metadata
            school_id = trigger_doc.get("schoolId") # schoolId in worker.py
            class_id = trigger_doc.get("classId")
            subject = trigger_doc.get("subject")
            timestamp = trigger_doc.get("timestamp")
            
            # Identify Date: timestamp (int) → createdAt (ISO/datetime) → now
            if isinstance(timestamp, (int, float)) and timestamp:
                dt = datetime.fromtimestamp(timestamp)
            else:
                ca = trigger_doc.get("createdAt")
                try:
                    dt = ca if isinstance(ca, datetime) else (
                        datetime.fromisoformat(str(ca).replace("Z", "+00:00")) if ca else datetime.utcnow()
                    )
                except Exception:
                    dt = datetime.utcnow()
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
            
            # Manual docs have no timestamp window → the query finds nothing; fall back
            # to just the trigger doc so single-doc / manual inserts still summarize.
            related_docs = await cursor.to_list(length=None) or [trigger_doc]
                
            from app.services.summary_blocks import best_transcript_text
            combined_text = "\n\n".join(
                t for t in (best_transcript_text(doc) for doc in related_docs) if t
            )
            if not combined_text.strip():
                logger.error(f"No transcript text in {transcript_id} (top-level or any provider)")
                return False

            # 3. Topic: use the doc's own topic if present, else identify via LLM
            topic_name = (trigger_doc.get("topic") or "").strip()
            chapter_name = (trigger_doc.get("chapter") or "").strip()
            if not topic_name:
                topic_info = await self._identify_topic(combined_text, class_id, subject)
                chapter_name = chapter_name or topic_info.get("chapter")
                topic_name = topic_info.get("topic")
            
            if not topic_name:
                logger.error(f"Could not identify topic for {subject} class {class_id}")
                return False

            # 3-5. Same unified path the API uses: ensure the classes_daily record
            # exists (create if absent, carrying this transcript's id), then generate
            # the approved summary_blocks from transcript + NCERT and stamp them in.
            class_num, section = _parse_class_id(class_id)
            date_iso = dt.date().isoformat()
            from app.services.summary_blocks import summarize_daily_from_transcript
            result = await summarize_daily_from_transcript(
                self.db, class_no=class_num, section=section, subject=subject, date=date_iso,
                topics=[topic_name], transcript_text=combined_text,
                transcript_id=transcript_id, force=force,
            )
            logger.info(f"✅ Summary from transcript {transcript_id} → daily {result.get('daily_id')} ({result})")
            return result

        except Exception as e:
            logger.error(f"Summary Generation Failed: {e}", exc_info=True)
            return False

    async def _identify_topic(self, text: str, class_id: str, subject: str) -> Dict[str, str]:
        """
        Ask LLM to identify the most likely NCERT Chapter and Topic from the transcript.
        """
        client = get_chat_client()
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
                model=settings.GEMINI_CHAT_MODEL,
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
        client = get_chat_client()

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
            model=settings.GEMINI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5
        )
        return resp.choices[0].message.content
