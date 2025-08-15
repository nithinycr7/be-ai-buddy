from fastapi import APIRouter, Depends, HTTPException, status
from ..core.security import api_key_guard
from ..db.mongo import get_db
from ..models.schemas import Student
from typing import List

router = APIRouter(prefix="/students", tags=["students"], dependencies=[Depends(api_key_guard)])

@router.post("", response_model=Student, status_code=201)
async def create_student(student: Student):
    print("I am here")
    db = await get_db()
    print(db)
    if await db.students.find_one({"student_id": student.student_id}):
        res = await db.students.find_one({"student_id": student.student_id})
        print (res,"thdd" )
        raise HTTPException(status_code=409, detail="student_id already exists")
    res = await db.students.insert_one(student.model_dump(by_alias=True, exclude_none=True))
    print(f"r//{res},{db}")
    student.id = str(res.inserted_id)
    return student

@router.get("/{student_id}", response_model=Student)
async def get_student(student_id: str):
    db = await get_db()
    doc = await db.students.find_one({"student_id": student_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found")
    return Student(**doc)

@router.get("", response_model=List[Student])
async def list_students(skip: int = 0, limit: int = 50):
    db = await get_db()
    cursor = db.students.find().skip(skip).limit(limit)
    return [Student(**d) async for d in cursor]
