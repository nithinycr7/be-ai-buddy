from __future__ import annotations


from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
import json
from app.core.config import settings
from bson import ObjectId
from app.services.ai import get_client
from openai import AzureOpenAI
from app.utils.validator import validate_and_fix, SCHEMA
from app.prompts.lesson_plan_prompt import lesson_plan_prompt, build_edit_prompt


_client: AzureOpenAI | None = None

def get_client() -> AzureOpenAI:
    global _client
    if _client is None:
          _client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version="2024-12-01-preview"
        )
    return _client

class LessonPlanService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.drafts = self.db.lecture_plan_drafts
        self.saved = self.db.lecture_plans
        self.versions = self.db.lecture_plan_versions

#     async def generate_plan(self, class_no: int, subject: str, chapter: str, teacher_id: str):
#         """
#         (A) generate_plan: Calls LLM, saves draft, creates initial version.
#         """
#         client = get_client()
        
#         prompt = f"""
# You are an expert teacher. Create a structured lecture plan for:
# Class: {class_no}, Subject: {subject}, Chapter: {chapter}.

# Return JSON with these fields:
# - learning_outcomes
# - warmup
# - explanation
# - activities
# - practice
# - assessment
# - homework
# - reflection

# Content should be detailed and NCERT aligned.
# """
#         resp = client.chat.completions.create(
#             model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
#             messages=[
#                 {"role": "system", "content": "You are a lesson planner. Return strictly JSON."},
#                 {"role": "user", "content": prompt},
#             ],
#             temperature=0.7,
#             response_format={"type": "json_object"}
#         )

#         try:
#             content = json.loads(resp.choices[0].message.content)
#             # Ensure all fields exist
#             plan_content = {
#                 "learning_outcomes": content.get("learning_outcomes", ""),
#                 "warmup": content.get("warmup", ""),
#                 "explanation": content.get("explanation", ""),
#                 "activities": content.get("activities", ""),
#                 "practice": content.get("practice", ""),
#                 "assessment": content.get("assessment", ""),
#                 "homework": content.get("homework", ""),
#                 "reflection": content.get("reflection", "")
#             }
#         except Exception:
#             raise ValueError("Failed to generate valid plan JSON")

#         # Save Draft
#         now = datetime.now(timezone.utc)
#         draft_doc = {
#             "teacher_id": teacher_id,
#             "class_no": class_no,
#             "subject": subject,
#             "chapter": chapter,
#             "plan": plan_content,
#             "is_saved": False,
#             "status": "draft",
#             "created_at": now,
#             "updated_at": now,
#             "lastAccessedAt": now
#         }
#         res = await self.drafts.insert_one(draft_doc)
#         draft_id = str(res.inserted_id)

#         # Create Version (Initial)
#         version_doc = {
#             "draft_id": draft_id,
#             "type": "initial",
#             "sections_modified": list(plan_content.keys()),
#             "prompt": "Initial Generation",
#             "previous_version": None,
#             "updated_version": plan_content,
#             "created_at": datetime.now(timezone.utc)
#         }
#         await self.versions.insert_one(version_doc)

#         # return {
#         #     "draft_id": draft_id,
#         #     "plan": plan_content
#         # }
#         draft_doc["_id"] = draft_id  # convert ObjectId to string
#         return draft_doc




    async def generate_plan(self, class_no, subject, chapter, teacher_id):
        client = get_client()

        system_message = (
            "You strictly output valid JSON. No explanations, no markdown, no extra text."
        )

        prompt = lesson_plan_prompt(class_no, subject, chapter)

        response_data = None
        max_attempts = 2

        for attempt in range(max_attempts):
            try:
                resp = client.chat.completions.create(
                    model= settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.4
                )

                raw = resp.choices[0].message.content.strip()
                parsed = json.loads(raw)
                print(f"DEBUG: LLM Raw Parsed Keys: {list(parsed.keys())}")
                response_data = validate_and_fix(parsed)
                print(f"DEBUG: Validated Data Keys: {list(response_data.keys())}")
                break

            except Exception as e:
                print(f"⚠️ LLM output failed attempt {attempt+1}: {e}")

        if not response_data:
            raise ValueError("❌ Failed: LLM did not provide valid JSON after retries.")

        now = datetime.now(timezone.utc)



        draft_doc = {
            "teacher_id": teacher_id,
            "class_no": class_no,
            "subject": subject,
            "chapter": chapter,
            "plan": response_data,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
            "lastAccessedAt": now
        }


        print("draft_doc:::", draft_doc)

        inserted = await self.drafts.insert_one(draft_doc)
        draft_id = str(inserted.inserted_id)
        draft_doc["_id"] = draft_id

        await self.versions.insert_one({
            "draft_id": draft_id,
            "type": "initial",
            "previous_version": None,
            "updated_version": response_data,
            "sections_modified": list(SCHEMA.keys()),
            "created_at": now
        })

        return draft_doc

#     async def edit_plan(self, draft_id: str, sections: list, instruction: str):
#         """
#         (B) edit_plan: Regenerate specific sections, update draft, log version.
#         """
#         draft = await self.drafts.find_one({"_id": ObjectId(draft_id)})
#         if not draft:
#             raise ValueError("Draft not found")

#         current_plan = draft["plan"]
        
#         # Prepare context for LLM
#         sections_context = {k: current_plan[k] for k in sections if k in current_plan}
        
#         client = get_client()
#         prompt = f"""
# You are editing a lecture plan.
# Here are the current sections you must modify:
# {json.dumps(sections_context, indent=2)}

# Teacher instruction:
# "{instruction}"

# Return ONLY the updated JSON for these sections.
# """
#         resp = client.chat.completions.create(
#             model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
#             messages=[
#                 {"role": "system", "content": "You edit lesson plans. Return strictly JSON."},
#                 {"role": "user", "content": prompt},
#             ],
#             temperature=0.7,
#             response_format={"type": "json_object"}
#         )

#         try:
#             updated_sections = json.loads(resp.choices[0].message.content)
#         except Exception:
#             raise ValueError("Failed to parse edited sections")

#         # Stitch updates
#         new_plan = current_plan.copy()
#         previous_version_snapshot = {}
        
#         for k, v in updated_sections.items():
#             if k in current_plan:
#                 previous_version_snapshot[k] = current_plan[k]
#                 new_plan[k] = v

#         # Update Draft
#         now = datetime.now(timezone.utc)
#         await self.drafts.update_one(
#             {"_id": ObjectId(draft_id)},
#             {
#                 "$set": {
#                     "plan": new_plan,
#                     "updated_at": now,
#                     "lastAccessedAt": now,
#                     "status": "editing"
#                 }
#             }
#         )

#         # Create Version
#         version_doc = {
#             "draft_id": draft_id,
#             "type": "edit",
#             "sections_modified": list(updated_sections.keys()),
#             "prompt": instruction,
#             "previous_version": previous_version_snapshot,
#             "updated_version": updated_sections,
#             "created_at": datetime.now(timezone.utc)
#         }
#         await self.versions.insert_one(version_doc)

#         return {
#             "draft_id": draft_id,
#             "plan": new_plan
#         }


    async def edit_plan(self, draft_id: str, sections: list, instruction: str):
        draft = await self.drafts.find_one({"_id": ObjectId(draft_id)})
        if not draft:
            raise ValueError("Draft not found")

        current_plan = draft["plan"]

        # Filter current sections to send to LLM
        sections_context = {
            key: current_plan[key] for key in sections if key in current_plan
        }

        if not sections_context:
            raise ValueError("No valid sections to update")

        # --- Create Prompt ---
        prompt = build_edit_prompt(sections_context, instruction)

        client = get_client()
        updated = None

        # Retry in case LLM returns bad JSON
        for attempt in range(2):
            try:
                response = client.chat.completions.create(
                    model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                    messages=[
                        {"role": "system", "content": "Only return valid JSON. Never explain."},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.4
                )

                raw = response.choices[0].message.content.strip()
                parsed = json.loads(raw)

                # Validate updated part only
                updated = {
                    sec: validate_and_fix({sec: parsed[sec]}).get(sec)
                    for sec in parsed.keys()
                    if sec in current_plan
                }

                break

            except Exception as e:
                print(f"⚠️ Edit attempt failed ({attempt+1}): {e}")

        if not updated:
            raise ValueError("❌ LLM failed to generate valid edited JSON after retries.")

        # Track previous snapshot for version history
        previous_snapshot = {sec: current_plan[sec] for sec in updated.keys()}

        # Merge into full plan safely
        new_plan = {**current_plan, **updated}

        now = datetime.now(timezone.utc)

        # Update stored draft
        await self.drafts.update_one(
            {"_id": ObjectId(draft_id)},
            {
                "$set": {
                    "plan": new_plan,
                    "updated_at": now,
                    "status": "edited"
                }
            }
        )

        # Create a version history entry
        await self.versions.insert_one({
            "draft_id": draft_id,
            "type": "section_edit",
            "sections_modified": list(updated.keys()),
            "teacher_instruction": instruction,
            "previous_version": previous_snapshot,
            "updated_version": updated,
            "created_at": now
        })

        return {
            "draft_id": draft_id,
            "plan": new_plan
        }


    async def save_plan(self, draft_id: str):
        """
        (C) save_plan: Promote draft to permanent storage.
        """
        draft = await self.drafts.find_one({"_id": ObjectId(draft_id)})
        if not draft:
            raise ValueError("Draft not found")

        now = datetime.now(timezone.utc)
        saved_doc = {
            "teacher_id": draft["teacher_id"],
            "class_no": draft["class_no"],
            "subject": draft["subject"],
            "chapter": draft["chapter"],
            "plan": draft["plan"],
            "summary": "Auto-generated summary", # Could generate this too
            "created_at": now,
            "updated_at": now,
            "lastAccessedAt": now
        }
        
        res = await self.saved.insert_one(saved_doc)
        
        # Mark draft as saved
        await self.drafts.update_one(
            {"_id": ObjectId(draft_id)},
            {"$set": {"is_saved": True, "status": "completed"}}
        )

        return {
            "plan_id": str(res.inserted_id),
            "status": "saved"
        }

    async def get_draft(self, draft_id: str):
        # Update lastAccessedAt when accessing draft
        await self.drafts.update_one(
            {"_id": ObjectId(draft_id)},
            {"$set": {"lastAccessedAt": datetime.now(timezone.utc)}}
        )
        draft = await self.drafts.find_one({"_id": ObjectId(draft_id)})
        if draft:
            draft["_id"] = str(draft["_id"])
            draft["type"] = "draft"
        return draft

    async def get_saved_plans(self, teacher_id: str):
        cursor = self.saved.find({"teacher_id": teacher_id})
        plans = await cursor.to_list(length=None)
        for p in plans:
            p["_id"] = str(p["_id"])
            p["type"] = "saved"
        return plans

    async def get_saved_plan(self, plan_id: str):
        # Update lastAccessedAt
        await self.saved.update_one(
            {"_id": ObjectId(plan_id)},
            {"$set": {"lastAccessedAt": datetime.now(timezone.utc)}}
        )
        plan = await self.saved.find_one({"_id": ObjectId(plan_id)})
        if plan:
            plan["_id"] = str(plan["_id"])
            plan["type"] = "saved"
        return plan
    
    async def update_last_accessed(self, plan_id: str, plan_type: str):
        """
        Update lastAccessedAt timestamp for a plan
        """
        collection = self.drafts if plan_type == "draft" else self.saved
        await collection.update_one(
            {"_id": ObjectId(plan_id)},
            {"$set": {"lastAccessedAt": datetime.now(timezone.utc)}}
        )
    
    async def get_recent_plans(self, teacher_id: str) -> Dict[str, List[Dict]]:
        """
        Get recent plans grouped by today and this week
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        
        # Fetch drafts (exclude saved ones)
        drafts_cursor = self.drafts.find({
            "teacher_id": teacher_id,
            "lastAccessedAt": {"$gte": week_start},
            "is_saved": {"$ne": True}
        })
        drafts = await drafts_cursor.to_list(length=None)
        
        # Combine and map to unified structure
        all_plans = []
        
        for draft in drafts:
            created_at = draft.get("created_at", now)
            last_accessed = draft.get("lastAccessedAt", created_at)
            updated_at = draft.get("updated_at")
            
            all_plans.append({
                "id": str(draft["_id"]),
                "type": "draft",
                "class": draft.get("class_no"),
                "subject": draft.get("subject"),
                "chapter": draft.get("chapter"),
                "updatedAt": updated_at.isoformat() if updated_at else None,
                "lastAccessedAt": last_accessed.isoformat() if last_accessed else now.isoformat()
            })
        
        # Group by today and this week
        today_plans = []
        this_week_plans = []
        
        for plan in all_plans:
           raw_ts = plan["lastAccessedAt"]
           # Handle potential Z suffix
           if isinstance(raw_ts, str):
               raw_ts = raw_ts.replace("Z", "+00:00")
               last_accessed = datetime.fromisoformat(raw_ts)
           else:
               last_accessed = raw_ts

           if last_accessed.tzinfo is None:
                last_accessed = last_accessed.replace(tzinfo=timezone.utc)
            
           if last_accessed >= today_start:
                today_plans.append(plan)
           else:       
                this_week_plans.append(plan)
        
        # Sort by lastAccessedAt descending (most recent first)
        today_plans.sort(key=lambda x: x["lastAccessedAt"], reverse=True)
        this_week_plans.sort(key=lambda x: x["lastAccessedAt"], reverse=True)
        
        return {
            "today": today_plans,
            "thisWeek": this_week_plans
        }