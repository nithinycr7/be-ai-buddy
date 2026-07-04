from fastapi import APIRouter, Depends, Query
from typing import Optional

from app.core.security import require_role
from app.services.teacher.insights_service import (
    InsightsService, InsightsResponse, get_insights_service,
)

router = APIRouter(dependencies=[Depends(require_role("teacher", "admin"))])


@router.get("", response_model=InsightsResponse)
async def get_class_insights(
    class_no: Optional[int] = Query(None, description="Class Number"),
    section: Optional[str] = Query(None, description="Section"),
    subject: Optional[str] = Query(None, description="Subject"),
    date_str: str = Query(..., alias="date", description="Date YYYY-MM-DD"),
    service: InsightsService = Depends(get_insights_service),
):
    return await service.class_insights(
        class_no=class_no, section=section, subject=subject, date_str=date_str)
