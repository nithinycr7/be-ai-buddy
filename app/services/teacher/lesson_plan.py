

from datetime import datetime, timezone
from typing import Optional, Dict, Any
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
import json
from app.core.config import settings
from bson import ObjectId
from app.services.ai import get_client
from openai import AzureOpenAI

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
            # "teacher": teacher,
            "section": section,
            "periods": periods,
        }



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
      

        
        # client = AzureOpenAI(
        #      api_key=settings.AZURE_OPENAI_API_KEY,
        #     azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        #     api_version="2024-12-01-preview"
        #     )

        client= get_client()
        print("model::::",settings.AZURE_OPENAI_CHAT_DEPLOYMENT,)

        prompt = f"""
You are an expert CBSE (NCERT) teacher and leacture planner and an aid to teacher.  
Your task is to generate a high-quality, structured lesson plan that is strictly aligned with the NCERT curriculum.  

### Input Details:
- Class: {class_no}  
- Subject: {subject}  
- Chapter: {chapter}  
- Section: {section}  
- Teacher: {teacher}  
- Total Periods: {periods}  

---

### Key Requirements:
1. *Strict NCERT Alignment*  
   - Base all content only on the official NCERT textbook for the given class and subject.  
   - Do not introduce external or advanced content beyond NCERT.  

2. *Comprehensive Lesson Plan*  
   - Include clear lesson objectives (knowledge, skills, and values students should gain).  
   - Mention pre-requisites (what students should already know).  
   - Specify teaching aids (blackboard, charts, models, digital resources, NCERT illustrations, etc.).  
   - Provide a period-wise plan dividing the chapter systematically into {periods} periods.  
   - Each period must include:  
     - Topics/subtopics to be covered  
     - Step-by-step sequence of teaching (how the class should proceed)  
     - Suggested methods (lecture, question-answer, discussion, activity, experiment, storytelling, group work, etc.)  
     - Activities/exercises for student engagement (role play, diagram drawing, experiments, problem-solving, peer discussion, worksheet practice, etc.)  
     - Homework/assignment ideas  
     - *Engagement Elements*: Must give 4 to 5 elaborate, interesting and relevant examples, stories, real-life hooks, practical applications, or inferences that help children relate to the topic and helps teacher for reference.  

3. *Pedagogical Flow*  
   - Begin each period with a recap of the previous class and a short warm-up/question or a hook (story, riddle, real-life scenario).  
   - Progress through explanation, examples, and interactive activities.  
   - Highlight practical applications or real-life connections wherever possible.  
   - End with a summary and formative assessment questions.  
   - Maintain age-appropriate language and CBSE methodology.  

4. *Assessment & Feedback*  
   - Suggest formative assessment methods (quiz, oral questioning, group activity, diagram labeling, NCERT exercise questions).  
   - Suggest summative assessment ideas at the end of the chapter (worksheet, short test, project, model making).  

5. *Quick Notes for Teachers*  
   - Important definitions, formulas, key terms.  
   - Keywords for revision.  
   - Important diagrams, charts, and examples from NCERT.  
   - Additional teacher tips (where students may struggle, misconceptions to address, how to connect the topic to real life).  
   - Short story hooks, analogies, or applications to spark curiosity.  

---

### Output Format:
**Rule**

Ensure that The response must be in *strict JSON format only* (no extra explanation/tags/info other than the actual output).  

Use the following schema:

{{
  "lecturePlan": {{
    "lessonObjectives": ["..."],
    "preRequisites": ["..."],
    "teachingAids": ["..."],
    "stepwisePlan": {{
      "Period 1": {{
        "topics": ["..."],
        "teachingSequence": ["..."],
        "methods": ["..."],
        "activities": ["..."],
        "homework": ["..."],
        "engagement": ["story/example/hook/practical application/inference"]
      }},
      "Period 2": {{
        "topics": ["..."],
        "teachingSequence": ["..."],
        "methods": ["..."],
        "activities": ["..."],
        "homework": ["..."],
        "engagement": ["story/example/hook/practical application/inference"]
      }}
    }},
    "assessmentIdeas": ["..."]
  }},
  "quickNotes": {{
    "keyDefinitions": ["..."],
    "keywords": ["..."],
    "diagramsExamples": ["..."],
    "importantPoints": ["..."],
    "teacherTips": ["..."],
    "storyHooks": ["..."],
    "practicalApplications": ["..."]
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
        #    response_format={"type": "json_object"}
        )

        print("resp:::",resp)

        # resp = client.chat.completions.create(
        #     model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        #     messages=_build_messages(req),
        #     temperature=req.temperature,
        #     max_tokens=req.max_tokens,
        # )

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



        # -----------------------------
        # Step 5: Save in DB
        # -----------------------------
        result = await self.db.lesson_plans.insert_one(plan_doc)
        plan_doc["_id"] = str(result.inserted_id)

        return {
            "from_db": False,
            "plan": plan_doc
        }