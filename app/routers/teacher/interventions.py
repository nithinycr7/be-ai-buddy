"""
Teacher-facing intervention insights (read-only).
Aggregates `student_interventions` into the dashboard's Learning-Gain table.
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional

from app.core.security import require_role
from app.services.teacher.interventions_service import (
    InterventionInsightsService, InterventionInsightsResponse,
    get_intervention_insights_service,
)

router = APIRouter(dependencies=[Depends(require_role("teacher", "admin"))])


@router.get("", response_model=InterventionInsightsResponse)
async def get_intervention_insights(
    class_no: Optional[int] = Query(None),
    section: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    date_str: str = Query(..., alias="date", description="Date YYYY-MM-DD"),
    service: InterventionInsightsService = Depends(get_intervention_insights_service),
):
    return await service.class_insights(
        class_no=class_no, section=section, subject=subject, date_str=date_str)
