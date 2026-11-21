"""HTTP endpoints for hospital analytics."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.routes import get_db
from app.auth import current_user, enforce_role_by_method, resource_access
from app.schemas import (
    AnalyticsComparisonRead,
    AnalyticsComparisonRequest,
    AnalyticsDepartmentsRead,
    AnalyticsFilters,
    AnalyticsInsightsRead,
    AnalyticsOccupancyRead,
    AnalyticsOverviewRead,
    AnalyticsPatientFlowRead,
    AnalyticsRunOptionsRead,
)
from app.services.analytics import (
    compare_analytics_runs,
    get_departments,
    get_occupancy,
    get_overview,
    get_patient_flow,
    get_rule_based_insights,
    list_analytics_runs,
)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"], dependencies=[Depends(current_user), Depends(enforce_role_by_method), Depends(resource_access)])


@router.get("/hospitals/{hospital_id}/runs", response_model=AnalyticsRunOptionsRead)
def hospital_analytics_runs(hospital_id: int, db: Session = Depends(get_db), user=Depends(current_user)) -> dict:
    return {"items": list_analytics_runs(db, hospital_id, owner_user_id=None if user.role == "admin" else user.id)}


@router.post("/runs/compare", response_model=AnalyticsComparisonRead)
def compare_runs(request: AnalyticsComparisonRequest, db: Session = Depends(get_db), user=Depends(current_user)) -> dict:
    return compare_analytics_runs(db, request, owner_user_id=None if user.role == "admin" else user.id)


@router.get("/hospitals/{hospital_id}/insights", response_model=AnalyticsInsightsRead)
def hospital_analytics_insights(
    hospital_id: int,
    filters: Annotated[AnalyticsFilters, Query()],
    db: Session = Depends(get_db),
    user=Depends(current_user),
) -> dict:
    return get_rule_based_insights(db, hospital_id, filters, owner_user_id=None if user.role == "admin" else user.id)


@router.get("/hospitals/{hospital_id}/overview", response_model=AnalyticsOverviewRead)
def hospital_analytics_overview(
    hospital_id: int,
    filters: Annotated[AnalyticsFilters, Query()],
    db: Session = Depends(get_db),
    user=Depends(current_user),
) -> dict:
    return get_overview(db, hospital_id, filters, owner_user_id=None if user.role == "admin" else user.id)


@router.get("/hospitals/{hospital_id}/occupancy", response_model=AnalyticsOccupancyRead)
def hospital_occupancy_analytics(
    hospital_id: int,
    filters: Annotated[AnalyticsFilters, Query()],
    db: Session = Depends(get_db),
    user=Depends(current_user),
) -> dict:
    return get_occupancy(db, hospital_id, filters, owner_user_id=None if user.role == "admin" else user.id)


@router.get("/hospitals/{hospital_id}/patient-flow", response_model=AnalyticsPatientFlowRead)
def hospital_patient_flow_analytics(
    hospital_id: int,
    filters: Annotated[AnalyticsFilters, Query()],
    db: Session = Depends(get_db),
    user=Depends(current_user),
) -> dict:
    return get_patient_flow(db, hospital_id, filters, owner_user_id=None if user.role == "admin" else user.id)


@router.get("/hospitals/{hospital_id}/departments", response_model=AnalyticsDepartmentsRead)
def hospital_department_analytics(
    hospital_id: int,
    filters: Annotated[AnalyticsFilters, Query()],
    db: Session = Depends(get_db),
    user=Depends(current_user),
) -> dict:
    return get_departments(db, hospital_id, filters, owner_user_id=None if user.role == "admin" else user.id)
