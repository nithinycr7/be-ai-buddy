from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from ..core.security import get_tenant, require_role, get_current_user, CurrentUser, assert_can_access_student
from ..db.repositories import StudentRepository, get_student_repo
from ..models.schemas import Student, UpdatePersonaRequest
from typing import List

router = APIRouter(prefix="/students", tags=["students"], dependencies=[Depends(require_role("student", "parent", "teacher", "admin"))])

@router.post("", response_model=Student, status_code=201)
async def create_student(student: Student, students: StudentRepository = Depends(get_student_repo), user: CurrentUser = Depends(require_role("admin"))):
    if await students.exists(student.student_id):
        raise HTTPException(status_code=409, detail="student_id already exists")
    doc = student.model_dump(by_alias=True, exclude_none=True)
    res = await students.insert_one(doc)
    student.id = str(res.inserted_id)
    return student

@router.get("/{student_id}", response_model=Student)
async def get_student(student_id: str, students: StudentRepository = Depends(get_student_repo), user: CurrentUser = Depends(get_current_user)):
    assert_can_access_student(user, student_id)
    doc = await students.get(student_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found")
    return Student(**doc)

@router.get("", response_model=List[Student])
async def list_students(skip: int = 0, limit: int = 50, students: StudentRepository = Depends(get_student_repo), user: CurrentUser = Depends(require_role("teacher", "admin"))):
    docs = await students.list(skip=skip, limit=limit)
    return [Student(**d) for d in docs]

@router.patch("/{student_id}/persona", response_model=Student)
async def update_student_persona(student_id: str, payload: UpdatePersonaRequest, students: StudentRepository = Depends(get_student_repo), user: CurrentUser = Depends(get_current_user)):
    """Upsert 5-attribute story persona for a student."""
    assert_can_access_student(user, student_id)
    if not await students.exists(student_id):
        raise HTTPException(status_code=404, detail="Student not found")
    await students.set_persona(student_id, payload.story_persona.model_dump())
    updated = await students.get(student_id)
    if "_id" in updated:
        updated["_id"] = str(updated["_id"])
    return Student(**updated)
