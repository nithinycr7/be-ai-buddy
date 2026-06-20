from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from ..core.security import api_key_guard, get_tenant
from ..db.mongo import get_db
from ..models.schemas import Student
from typing import List
from ..models.schemas import Student, UpdatePersonaRequest
from bson import ObjectId

router = APIRouter(prefix="/students", tags=["students"], dependencies=[Depends(api_key_guard)])

@router.post("", response_model=Student, status_code=201)
async def create_student(student: Student, tenant: str = Depends(get_tenant)):
    db = await get_db()
    if await db.students.find_one({"student_id": student.student_id, "tenant": tenant}):
        raise HTTPException(status_code=409, detail="student_id already exists")
    doc = student.model_dump(by_alias=True, exclude_none=True)
    doc["tenant"] = tenant
    res = await db.students.insert_one(doc)
    student.id = str(res.inserted_id)
    return student

@router.get("/{student_id}", response_model=Student)
async def get_student(student_id: str, tenant: str = Depends(get_tenant)):
    db = await get_db()
    doc = await db.students.find_one({"student_id": student_id, "tenant": tenant})
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found")
    return Student(**doc)

@router.get("", response_model=List[Student])
async def list_students(skip: int = 0, limit: int = 50, tenant: str = Depends(get_tenant)):
    db = await get_db()
    cursor = db.students.find({"tenant": tenant}).skip(skip).limit(limit)
    return [Student(**d) async for d in cursor]

@router.patch("/{student_id}/persona", response_model=Student)
async def update_student_persona(student_id: str, payload: UpdatePersonaRequest, tenant: str = Depends(get_tenant)):
    """
    Upsert 5-attribute story persona for a student.
    """
    db = await get_db()
    key = {"student_id": student_id, "tenant": tenant}
    doc = await db.students.find_one(key)
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found")

    # set the new structured persona
    await db.students.update_one(key, {"$set": {"story_persona": payload.story_persona.model_dump()}})
    updated = await db.students.find_one(key)
    if "_id" in updated and isinstance(updated["_id"], ObjectId):
        updated["_id"] = str(updated["_id"])
    return Student(**updated)