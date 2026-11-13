"""HTTP endpoints for hospital analytics."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.routes import get_db
from app.schemas import (
    AnalyticsDepartmentsRead,
    AnalyticsFilters,
    AnalyticsOccupancyRead,
    AnalyticsOverviewRead,
    AnalyticsPatientFlowRead,
)
from app.services.analytics import get_departments, get_occupancy, get_overview, get_patient_flow

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/hospitals/{hospital_id}/overview", response_model=AnalyticsOverviewRead)
def hospital_analytics_overview(
    hospital_id: int,
    filters: Annotated[AnalyticsFilters, Query()],
    db: Session = Depends(get_db),
) -> dict:
    return get_overview(db, hospital_id, filters)


@router.get("/hospitals/{hospital_id}/occupancy", response_model=AnalyticsOccupancyRead)
def hospital_occupancy_analytics(
    hospital_id: int,
    filters: Annotated[AnalyticsFilters, Query()],
    db: Session = Depends(get_db),
) -> dict:
    return get_occupancy(db, hospital_id, filters)


@router.get("/hospitals/{hospital_id}/patient-flow", response_model=AnalyticsPatientFlowRead)
def hospital_patient_flow_analytics(
    hospital_id: int,
    filters: Annotated[AnalyticsFilters, Query()],
    db: Session = Depends(get_db),
) -> dict:
    return get_patient_flow(db, hospital_id, filters)


@router.get("/hospitals/{hospital_id}/departments", response_model=AnalyticsDepartmentsRead)
def hospital_department_analytics(
    hospital_id: int,
    filters: Annotated[AnalyticsFilters, Query()],
    db: Session = Depends(get_db),
) -> dict:
    return get_departments(db, hospital_id, filters)
