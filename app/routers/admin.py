from __future__ import annotations
from typing import List, Optional
from fastapi import APIRouter, Depends, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from ..db.mongo import get_db
from ..core.security import require_role, get_current_user, CurrentUser
from ..services.admin_service import AdminService, get_admin_service
from ..services import provisioning_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("admin"))])


@router.get("/teacher-performance")
async def teacher_performance(
    teacher_email: str,
    service: AdminService = Depends(get_admin_service),
):
    return await service.teacher_performance(teacher_email)


class RosterRow(BaseModel):
    name: str
    class_no: int | str
    section: str
    roll_no: Optional[str] = None
    parent_email: Optional[str] = None
    parent_phone: Optional[str] = None


class RosterImportRequest(BaseModel):
    rows: List[RosterRow]


@router.post("/students/import")
async def import_roster(
    body: RosterImportRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Bulk-create students (+ parent invites) from a roster. Returns the generated
    code+PIN per student ONCE, for printable login slips (PINs are hashed at rest)."""
    origin = request.headers.get("origin") or ""
    return await provisioning_service.import_roster(
        db, tenant=user.tenant, rows=[r.model_dump() for r in body.rows],
        created_by=user.user_id, base_url=origin,
    )
