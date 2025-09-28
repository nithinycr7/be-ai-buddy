from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from app.services.user import UserService
from app.auth.password_handler import hash_password , generate_password
from app.models.user import UserCreate
class SchoolService:


     def __init__(self, db: AsyncIOMotorDatabase,user_service: UserService):
        self.db = db
        self.user_service = user_service


        # Helper method to extract admin data (Best practice for cleaner code)
 
   #   def _extract_admin_payload(self, school_payload, generated_password):
   #      """Prepares the payload for UserService based on the school data."""
        
   #      # ⭐️ Admin username is the school name (lowercase, no spaces)
   #      admin_username = school_payload.name.replace(" ", "").lower()
        
   #      return {
   #          "school_id": school_payload.school_id,
   #          "user_id": admin_username, # The unique identifier
   #          "username": school_payload.name, # A display name (optional)
   #          "email": school_payload.admin_email,
   #          "first_name": school_payload.admin_first_name,
   #          "last_name": school_payload.admin_last_name,
   #          "password": generated_password, # The plain text password
   #          "roles": ["admin"]
   #      }


     def _extract_admin_payload(self, school_payload, generated_password):
      # Returns a UserCreate Pydantic model instead of a dict
      return UserCreate(
        school_id=school_payload.school_id,
        user_id=school_payload.school_id,
        username=school_payload.name,
        email=school_payload.admin_email,
        first_name=school_payload.admin_first_name,
        last_name=school_payload.admin_last_name,
        password=generated_password,
        roles=["admin"]
    )

     async def create_school(self, payload):
       
       school_id_value = payload.school_id # ⭐️ Safely extract the ID early ⭐️

       existing = await self.db.schools.find_one({"school_id": school_id_value})
       if existing:
        raise HTTPException(status_code=400, detail="School ID already exists")

               # ⭐️ 1. Generate Password and Username
       plain_password = generate_password() # Utility function needed
        
        # Prepare and insert the school document (excluding admin user fields)
       school_doc = payload.dict(exclude={"admin_email", "admin_first_name", "admin_last_name"}) 
       school_doc["created_at"] = datetime.utcnow()

       # --- Transaction-like Logic Starts Here ---
       try:
            # 1. Create the School
            await self.db.schools.insert_one(school_doc)

            # 2. Prepare Admin User Data
            admin_user_payload = self._extract_admin_payload(payload,plain_password)

            # 3. Create the Admin User using the injected UserService
            # This call will handle password hashing and insertion into the 'users' collection
            await self.user_service.create_user(admin_user_payload)

            # 4. Success: Log the password and send email
            # IMPORTANT: The UserService should ideally handle the email logic
            
            # TODO: Call your email service here using admin_user_payload["email"] 
            # and plain_password
            print(f"Initial Admin Password for {admin_user_payload.user_id}: {plain_password}") 


       except HTTPException as e:
            # Error during school or user creation: attempt to rollback the school creation
            print(f"Error during school onboarding. Attempting to rollback school: {school_id_value}. Error: {e.detail}")
            
            # Rollback: Delete the school document if it was created
            await self.db.schools.delete_one({"school_id": school_id_value})
            
            # Re-raise the exception to the API endpoint
            raise HTTPException(
                status_code=500, 
                detail=f"School onboarding failed. School deleted. Detail: {e.detail}"
            )
            
       except Exception as e:
             # Handle other unexpected errors
            await self.db.schools.delete_one({"school_id": school_id_value})
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred during onboarding: {str(e)}")


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
