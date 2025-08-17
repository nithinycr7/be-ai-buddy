
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.models.question import Question
from typing import List

class QuestionService:
     def __init__(self, db: AsyncIOMotorDatabase):
         self.collection = db["questions"]



     async def create_question(self, question_data: dict) -> Question:
        """Insert a new question into the DB and return Question model"""

        # Validate using Pydantic model
        question = Question(**question_data)

        # Convert to dict for Mongo insert
        data = question.dict(by_alias=True, exclude_unset=True)

        # ❌ Remove `_id` if None (let Mongo generate)
        if "_id" in data and data["_id"] is None:
            del data["_id"]

        # Insert into MongoDB
        result = await self.collection.insert_one(data)

        # Set the generated ObjectId back into the model
        question.id = str(result.inserted_id)

        return question



     async def get_all_questions(self) -> list[Question]:
       questions = await self.collection.find().to_list(length=None)
      
       return [Question(**q) for q in questions]
         