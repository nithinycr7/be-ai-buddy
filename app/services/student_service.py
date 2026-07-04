"""Student business logic. Sits between the router and the repository.

Dependency flow: router -> StudentService -> StudentRepository. The service holds
the rules (uniqueness, ownership, not-found) and raises domain exceptions; it never
touches Motor and never raises HTTPException.
"""
from __future__ import annotations

from typing import List

from fastapi import Depends

from ..core.exceptions import ConflictError, NotFoundError
from ..core.security import CurrentUser, assert_can_access_student
from ..db.repositories import StudentRepository, get_student_repo
from ..models.schemas import Student


def _to_student(doc: dict) -> Student:
    """Boundary conversion: stringify Mongo's ObjectId _id before it hits the
    Pydantic response model (which types id as str). Routes never see ObjectId."""
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return Student(**doc)


class StudentService:
    def __init__(self, repo: StudentRepository):
        self.repo = repo

    async def create(self, student: Student) -> Student:
        if await self.repo.exists(student.student_id):
            raise ConflictError("student_id already exists")
        res = await self.repo.insert_one(student.model_dump(by_alias=True, exclude_none=True))
        student.id = str(res.inserted_id)
        return student

    async def get(self, student_id: str, *, requester: CurrentUser) -> Student:
        assert_can_access_student(requester, student_id)
        doc = await self.repo.get(student_id)
        if not doc:
            raise NotFoundError("Student not found")
        return _to_student(doc)

    async def list(self, *, skip: int = 0, limit: int = 50) -> List[Student]:
        docs = await self.repo.list(skip=skip, limit=limit)
        return [_to_student(d) for d in docs]

    async def update_persona(self, student_id: str, persona: dict, *, requester: CurrentUser) -> Student:
        assert_can_access_student(requester, student_id)
        if not await self.repo.exists(student_id):
            raise NotFoundError("Student not found")
        await self.repo.set_persona(student_id, persona)
        doc = await self.repo.get(student_id)
        return _to_student(doc)


def get_student_service(repo: StudentRepository = Depends(get_student_repo)) -> StudentService:
    return StudentService(repo)
