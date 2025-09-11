

from datetime import datetime, timezone
from typing import Optional, Dict, Any
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
import json
from openai import AzureOpenAI
from app.core.config import settings
from bson import ObjectId

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
        self.collection = self.db.lesson_plans

    async def create_or_update_lesson_plan(
        self,
        teacher_id: str,
        class_no: int,
        subject: str,
        chapter: str,
        section: Optional[str],
        lecture_plan: Optional[Dict[str, Any]] = None,
        quick_notes: Optional[Dict[str, Any]] = None
    ):
        """
        Create a new lesson plan if it does not exist, otherwise update the existing one.
        """

        query = {
            "teacher_id": ObjectId(teacher_id),
            "class_no": class_no,
            "subject": subject,
            "chapter": chapter,
        }
        if section:
            query["section"] = section

        update_doc = {
            "$set": {
                "lecturePlan": lecture_plan,
                "quickNotes": quick_notes,
                "updated_at": datetime.now(timezone.utc),
            },
            "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
            },
        }

        result = await self.collection.update_one(query, update_doc, upsert=True)

        if result.upserted_id:
            return {"lessonPlanId": str(result.upserted_id), "status": "created"}
        else:
            existing = await self.collection.find_one(query)
            return {"lessonPlanId": str(existing["_id"]), "status": "updated"}

    async def get_lesson_plan(
        self,
        teacher_id: str,
        class_no: int,
        subject: str,
        chapter: str,
        section: Optional[str] = None
    ):
        """
        Fetch a specific lesson plan for teacher/class/subject/chapter.
        """
        query = {
            "teacher_id": ObjectId(teacher_id),
            "class_no": class_no,
            "subject": subject,
            "chapter": chapter,
        }
        if section:
            query["section"] = section

        lesson_plan = await self.collection.find_one(query)
        if not lesson_plan:
            return None

        lesson_plan["_id"] = str(lesson_plan["_id"])
        lesson_plan["teacher_id"] = str(lesson_plan["teacher_id"])
        return lesson_plan

    async def get_all_lesson_plans(self, teacher_id: str):
        """
        Fetch all lesson plans for a teacher.
        """
        cursor = self.collection.find({"teacher_id": ObjectId(teacher_id)})
        plans = await cursor.to_list(length=None)

        for p in plans:
            p["_id"] = str(p["_id"])
            p["teacher_id"] = str(p["teacher_id"])

        return plans

    async def delete_lesson_plan(self, lesson_plan_id: str):
        """
        Delete a lesson plan by ID.
        """
        result = await self.collection.delete_one({"_id": ObjectId(lesson_plan_id)})
        return {"deleted": result.deleted_count > 0}

    async def generate_lesson_plan(
        self,
        class_no: int,
        subject: str,
        chapter: str,
        teacher: str,
        section: str,
        periods: int
    ):
        
        print("class_no::::",class_no)
        """
        1. Check DB for existing plan
        2. If found -> return it
        3. Else -> generate using LLM, save in DB, return
        """

        # -----------------------------
        # Step 1: Check DB
        # -----------------------------
        query = {
            "class_no": class_no,
            "subject": subject,
            "chapter": chapter,
            "teacher": ObjectId(teacher),
            "section": section,
            "periods": periods,
        }


        print("query::::",query)

        existing_plan = await self.db.lesson_plans.find_one(query)
        if existing_plan:
            existing_plan["_id"] = str(existing_plan["_id"])
            return {
                "from_db": True,
                "plan": existing_plan
            }


        # -----------------------------
        # Step 2: Generate using LLM
        # -----------------------------
        print("existing_plan::::",existing_plan)
        
        client = get_client()
        print("client::::",client)

        prompt = f"""
      You are an expert CBSE (NCERT) teacher preparing structured lesson plans.  
      Generate a **lesson plan strictly aligned with NCERT curriculum**.

     Details of the request:  
      - Class: {class_no}  
      - Subject: {subject}  
      - Chapter: {chapter}  
- Section: {section}  
- Teacher: {teacher}  
- Total Periods: {periods}  


### Requirements:
1. Base the lesson plan on **NCERT textbook content only** for the given class and chapter.  
2. Keep the plan **age-appropriate** and aligned with **CBSE teaching methods**.  
3. Divide the content **period-wise**. Each period should include:  
   - Topics to be taught  
   - Suggested teaching methods (e.g., lecture, activity, experiment, discussion)  
   - Activities/exercises for student engagement  
4. Provide **objectives, prerequisites, teaching aids, and assessment ideas**.  
5. Include **Quick Notes for teachers** (important points, definitions, examples, keywords, diagrams).  
6. Keep formatting in **strict JSON only**. Do not add extra explanation.  
7. Do not include topics outside NCERT.  

        Output must be STRICT JSON in this format:
        {{
          "lecturePlan": {{
            "lessonObjectives": ["..."],
            "preRequisites": ["..."],
            "teachingAids": ["..."],
            "stepwisePlan": {{
              "Period 1": "...",
              "Period 2": "..."
            }},
            "assessmentIdeas": ["..."]
          }},
          "quickNotes": {{
            "keyDefinitions": ["..."],
            "keywords": ["..."],
            "diagramsExamples": ["..."],
            "importantPoints": ["..."]
          }}
        }}
        """

        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You create structured lesson plans for school teachers."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )

        generated_plan = resp.choices[0].message.content

        # -----------------------------
        # Step 3: Parse JSON
        # -----------------------------
        try:
            plan_doc = json.loads(generated_plan)
        except json.JSONDecodeError:
            raise ValueError("LLM did not return valid JSON")

        # -----------------------------
        # Step 4: Add metadata
        # -----------------------------
        plan_doc.update({
            "class_no": class_no,
            "subject": subject,
            "chapter": chapter,
            "teacher": teacher,
            "section": section,
            "periods": periods,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })

        print("plan_doc::::",plan_doc)

        # -----------------------------
        # Step 5: Save in DB
        # -----------------------------
        result = await self.db.lesson_plans.insert_one(plan_doc)
        plan_doc["_id"] = str(result.inserted_id)

        return {
            "from_db": False,
            "plan": plan_doc
        }