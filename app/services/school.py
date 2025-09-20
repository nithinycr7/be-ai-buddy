from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime

class SchoolService:


     def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

     async def create_school(self, payload):
       existing = await self.db.schools.find_one({"school_id": payload.school_id})
       if existing:
        raise HTTPException(status_code=400, detail="School ID already exists")

       school_doc = payload.dict()
       school_doc["created_at"] = datetime.utcnow()
       await self.db.schools.insert_one(school_doc)
       return {"message": "School onboarded successfully"}
      # New method to get the list of schools
    
     async def get_schools(self, skip: int = 0, limit: int = 50):
        """
        Fetch a list of schools with optional pagination.
        :param skip: Number of documents to skip
        :param limit: Maximum number of documents to return
        """
        cursor = self.db.schools.find().skip(skip).limit(limit)

        print("cursor::",cursor)
        schools = await cursor.to_list(length=limit)
        # Convert _id to string for JSON serialization
        for school in schools:
         if "_id" in school:
            school["_id"] = str(school["_id"])

        return schools
