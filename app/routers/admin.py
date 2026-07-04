from __future__ import annotations
from fastapi import APIRouter, Depends
from ..core.security import require_role
from ..services.admin_service import AdminService, get_admin_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("admin"))])


@router.get("/teacher-performance")
async def teacher_performance(
    teacher_email: str,
    service: AdminService = Depends(get_admin_service),
):
    return await service.teacher_performance(teacher_email)
