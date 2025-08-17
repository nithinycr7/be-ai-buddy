# services/quiz_service.py
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

class QuizService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create_quiz_for_topic(self, subject: str, topic: str,class_no:str):
        # fetch questions
        cursor = self.db.questions.find({"subject": subject, "topic": topic, "class_no":class_no})
        question_docs = await cursor.to_list(length=None)

        print("cursor:::",question_docs,subject,topic,class_no)

        question_ids = [str(q["_id"]) for q in question_docs]

        if not question_ids:
            return {"error": "No questions found for this topic"}

        quiz_doc = {
            "subject": subject,
            "topic": topic,
            "questions": question_ids,
            "class_no":class_no,
            "created_at": datetime.now(timezone.utc)
        }

        result = await self.db.quizzes.insert_one(quiz_doc)
        return {
            "quizId": str(result.inserted_id),
            "questionsCount": len(question_ids)
        }

    async def get_all_quizzes(self):
     quizzes = await self.db.quizzes.find().to_list(length=None)
     return [{"id": str(q["_id"]), **q} for q in quizzes]
    
  
 

    async def get_quizzes_by_topic(self, topic: str):
      
    
       # 1. Fetch quizzes by topic
       quizzes = await self.db.quizzes.find({"topic": topic}).to_list(100)
       result = []

       for quiz in quizzes:
        question_ids = quiz.get("questions", [])
        question_object_ids = [ObjectId(qid) for qid in question_ids]

        # 2. Fetch full question documents
        questions = await self.db.questions.find({"_id": {"$in": question_object_ids}}).to_list(length=len(question_object_ids))

        # 3. Convert _id of questions to str
        questions_data = [{**q, "_id": str(q["_id"])} for q in questions]

        # 4. Prepare final quiz data
        quiz_data = {**quiz, "_id": str(quiz["_id"]), "questions": questions_data}
        result.append(quiz_data)

       
       return result
