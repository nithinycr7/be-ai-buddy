from __future__ import annotations
from fastapi import APIRouter, Depends
from typing import List
from ..core.security import require_role, get_current_user, CurrentUser
from ..services.student_service import StudentService, get_student_service
from ..models.schemas import Student, UpdatePersonaRequest

router = APIRouter(prefix="/students", tags=["students"], dependencies=[Depends(require_role("student", "parent", "teacher", "admin"))])

@router.post("", response_model=Student, status_code=201)
async def create_student(
    student: Student,
    service: StudentService = Depends(get_student_service),
    user: CurrentUser = Depends(require_role("admin")),
):
    return await service.create(student)

@router.get("/{student_id}", response_model=Student)
async def get_student(
    student_id: str,
    service: StudentService = Depends(get_student_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.get(student_id, requester=user)

@router.get("", response_model=List[Student])
async def list_students(
    skip: int = 0,
    limit: int = 50,
    service: StudentService = Depends(get_student_service),
    user: CurrentUser = Depends(require_role("teacher", "admin")),
):
    return await service.list(skip=skip, limit=limit)

@router.patch("/{student_id}/persona", response_model=Student)
async def update_student_persona(
    student_id: str,
    payload: UpdatePersonaRequest,
    service: StudentService = Depends(get_student_service),
    user: CurrentUser = Depends(get_current_user),
):
    return await service.update_persona(student_id, payload.story_persona.model_dump(), requester=user)
