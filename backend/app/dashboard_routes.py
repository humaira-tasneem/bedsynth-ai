"""Authenticated user and administrator dashboard summaries."""

import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.auth import admin_user, current_user
from app.database import get_db
from app.models import (Admission, Bed, BedAssignment, BedTransfer, BedTurnaround, Department, Discharge,
                        GenerationRun, Hospital, OccupancySnapshot, SyntheticPatient, User, WaitingQueueEntry, Workspace)
from app.services.analytics import get_run_snapshot_summary, scenario_name_for_run
from app.services.datasets import _list_item, _record_counts, _validation_summaries

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"], dependencies=[Depends(current_user)])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["administration"], dependencies=[Depends(admin_user)])


def _record_total(counts) -> int:
    return sum((getattr(counts, field) or 0) for field in (
        "patients", "admissions", "discharges", "bed_assignments", "bed_transfers",
        "occupancy_snapshots", "waiting_queue", "bed_turnaround",
    ))


@router.get("/user")
def user_dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Summarize only non-deleted runs owned by the signed-in user."""
    run_filter = (
        GenerationRun.owner_user_id == user.id,
        GenerationRun.guest_session_id.is_(None),
        GenerationRun.deleted_at.is_(None),
        GenerationRun.status == "completed",
        Workspace.is_shared.is_(True),
    )
    total_datasets = int(db.scalar(select(func.count(GenerationRun.run_id)).join(
        Workspace, Workspace.id == GenerationRun.workspace_id
    ).where(*run_filter)) or 0)
    record_models = (SyntheticPatient, Admission, Discharge, BedAssignment, BedTransfer, OccupancySnapshot)
    records = sum(db.scalar(select(func.count(model.id)).join(
        GenerationRun, and_(GenerationRun.run_id == model.run_id,
                            GenerationRun.workspace_id == model.workspace_id,
                            GenerationRun.hospital_id == model.hospital_id)
    ).join(Workspace, Workspace.id == GenerationRun.workspace_id).where(*run_filter)) or 0 for model in record_models)
    records += sum(db.scalar(select(func.coalesce(func.sum(column), 0)).join(
        Workspace, Workspace.id == GenerationRun.workspace_id
    ).where(*run_filter)) or 0 for column in (GenerationRun.waiting_queue_count, GenerationRun.bed_turnaround_count))
    runs = list(db.scalars(select(GenerationRun).join(Workspace, Workspace.id == GenerationRun.workspace_id)
        .where(GenerationRun.owner_user_id == user.id, GenerationRun.guest_session_id.is_(None),
               GenerationRun.deleted_at.is_(None), Workspace.is_shared.is_(True))
        .order_by(GenerationRun.started_at.desc(), GenerationRun.run_id.desc()).limit(5)).all())
    counts = _record_counts(db, runs)
    hospital_names = {row.id: row.name for row in db.scalars(select(Hospital).where(
        Hospital.id.in_({run.hospital_id for run in runs}) if runs else False,
    )).all()}
    latest_occupancy = None
    latest_snapshot_run = db.scalar(select(GenerationRun).join(Workspace, Workspace.id == GenerationRun.workspace_id)
        .where(*run_filter, select(OccupancySnapshot.id).where(OccupancySnapshot.run_id == GenerationRun.run_id).exists())
        .order_by(GenerationRun.started_at.desc(), GenerationRun.run_id.desc()).limit(1))
    if latest_snapshot_run:
        latest_occupancy = get_run_snapshot_summary(db, latest_snapshot_run)
    recent = []
    validations = _validation_summaries(db, runs)
    for run in runs:
        summary = _list_item(run, hospital_names.get(run.hospital_id, "Unavailable"), counts[run.run_id], validations.get(run.run_id, []))
        recent.append(summary.model_dump(mode="json"))
    return {
        "user_email": user.email,
        "total_datasets": total_datasets,
        "total_generated_records": records,
        "latest_occupancy_pct": latest_occupancy["latest_occupancy_pct"] if latest_occupancy else None,
        "latest_occupancy_date": latest_occupancy["latest_snapshot_date"] if latest_occupancy else None,
        "recent_runs": recent,
    }


@admin_router.get("/dashboard")
def admin_dashboard(db: Session = Depends(get_db)) -> dict:
    """Platform-wide counts and recent activity; protected by admin_user."""
    total_users = db.scalar(select(func.count(User.id))) or 0
    active_users = db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0
    shared_hospitals = select(Hospital.id).join(Workspace, Workspace.id == Hospital.workspace_id).where(
        Workspace.is_shared.is_(True), Hospital.is_archived.is_(False),
    )
    hospital_ids = set(db.scalars(shared_hospitals).all())
    departments = db.scalar(select(func.count(Department.id)).where(
        Department.hospital_id.in_(hospital_ids) if hospital_ids else False,
        Department.is_archived.is_(False),
    )) or 0
    beds = db.scalar(select(func.count(Bed.id)).where(
        Bed.hospital_id.in_(hospital_ids) if hospital_ids else False,
        Bed.status != "retired",
    )) or 0
    run_filter = (
        GenerationRun.guest_session_id.is_(None),
        GenerationRun.deleted_at.is_(None),
    )
    total_runs = db.scalar(select(func.count(GenerationRun.run_id)).where(*run_filter)) or 0
    completed_filter = (*run_filter, GenerationRun.status == "completed")
    record_models = (SyntheticPatient, Admission, Discharge, BedAssignment, BedTransfer, OccupancySnapshot)
    total_records = sum(db.scalar(select(func.count(model.id)).join(
        GenerationRun, and_(GenerationRun.run_id == model.run_id,
                            GenerationRun.workspace_id == model.workspace_id,
                            GenerationRun.hospital_id == model.hospital_id)
    ).where(*completed_filter)) or 0 for model in record_models)
    total_records += sum(db.scalar(select(func.coalesce(func.sum(column), 0)).where(*completed_filter)) or 0
                         for column in (GenerationRun.waiting_queue_count, GenerationRun.bed_turnaround_count))
    recent_runs = list(db.scalars(select(GenerationRun).where(*run_filter)
        .order_by(GenerationRun.started_at.desc(), GenerationRun.run_id.desc()).limit(8)).all())
    counts = _record_counts(db, recent_runs)
    hospital_names = {row.id: row.name for row in db.scalars(select(Hospital).where(
        Hospital.id.in_({run.hospital_id for run in recent_runs}) if recent_runs else False,
    )).all()}
    owner_ids = {run.owner_user_id for run in recent_runs if run.owner_user_id is not None}
    owners = {row.id: row.email for row in db.scalars(select(User).where(User.id.in_(owner_ids) if owner_ids else False)).all()}
    return {
        "total_registered_users": total_users,
        "active_users": active_users,
        "shared_hospitals": len(hospital_ids),
        "departments": departments,
        "beds": beds,
        "generation_runs": int(total_runs),
        "generated_records": total_records,
        "recent_activity": [{
            "run_id": run.run_id,
            "hospital_name": hospital_names.get(run.hospital_id, "Unavailable"),
            "owner_email": owners.get(run.owner_user_id) if run.owner_user_id is not None else None,
            "started_at": run.started_at.isoformat(),
            "status": run.status,
            "scenario_name": scenario_name_for_run(run),
            "record_count": _record_total(counts[run.run_id]),
        } for run in recent_runs],
    }


@admin_router.get("/datasets")
def admin_datasets(
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    hospital_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, pattern="^(generating|completed|failed)$"),
    ownership: str | None = Query(default=None, pattern="^(owned|historical)$"),
    include_deleted: bool = False,
) -> dict:
    """Search across platform runs, including historical unowned runs."""
    query = select(GenerationRun, Hospital.name, User.email).join(
        Hospital, (Hospital.id == GenerationRun.hospital_id) & (Hospital.workspace_id == GenerationRun.workspace_id),
    ).outerjoin(User, User.id == GenerationRun.owner_user_id).where(GenerationRun.guest_session_id.is_(None))
    if not include_deleted:
        query = query.where(GenerationRun.deleted_at.is_(None))
    if hospital_id is not None:
        query = query.where(GenerationRun.hospital_id == hospital_id)
    if status:
        query = query.where(GenerationRun.status == status)
    if ownership == "owned":
        query = query.where(GenerationRun.owner_user_id.is_not(None))
    elif ownership == "historical":
        query = query.where(GenerationRun.owner_user_id.is_(None))
    if q:
        needle = f"%{q.strip()}%"
        query = query.where(or_(GenerationRun.run_id.ilike(needle), Hospital.name.ilike(needle), User.email.ilike(needle)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pairs = list(db.execute(query.order_by(GenerationRun.started_at.desc(), GenerationRun.run_id.desc())
                             .offset((page - 1) * page_size).limit(page_size)))
    runs = [run for run, _hospital, _owner in pairs]
    counts = _record_counts(db, runs)
    validations = _validation_summaries(db, runs)
    items = []
    for run, hospital_name, owner_email in pairs:
        item = _list_item(run, hospital_name, counts[run.run_id], validations.get(run.run_id, []))
        items.append({**item.model_dump(mode="json"), "owner_user_id": run.owner_user_id,
                      "owner_email": owner_email, "deleted_at": run.deleted_at.isoformat() if run.deleted_at else None})
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": math.ceil(total / page_size) if total else 0}
