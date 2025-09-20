from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from app.auth.password_handler import hash_password , generate_password
from typing import List, Optional

class UserService:


     def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

     async def create_user(self, payload):
      # Ensure school exists
      school = await self.db.schools.find_one({"school_id": payload.school_id})
      if not school:
        raise HTTPException(status_code=404, detail="School not found")

      # Check for duplicate user_id
      existing = await self.db.users.find_one({"user_id": payload.user_id, "school_id": payload.school_id})
      if existing:
        raise HTTPException(status_code=400, detail="User ID already exists in this school")

              # Generate password if not provided
      plain_password = getattr(payload, "password", None) or generate_password()

      user_doc = payload.dict()
      user_doc = payload.dict(exclude={"password"})
      user_doc["hashed_password"] = hash_password(plain_password)

      user_doc["created_at"] = datetime.utcnow()
      await self.db.users.insert_one(user_doc)

      print("plain_password:::",plain_password)

      #TODO: send password via email 

      return {"message": "User created successfully"}

    

     async def get_users(
        self,
        school_id: str,
        role: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[dict]:
        """
        Fetch users for a given school.
        Optionally filter by role (teacher/student/parent/admin).
        """
        query = {"school_id": school_id}
        if role:
            query["roles"] = {"$in": [role]}  # matches any user having this role

        cursor = self.db.users.find(query).skip(skip).limit(limit)
        users = []
        async for user in cursor:
            user["_id"] = str(user["_id"])  # convert ObjectId to string
            del user["hashed_password"]     # never expose password
            users.append(user)

        return users

