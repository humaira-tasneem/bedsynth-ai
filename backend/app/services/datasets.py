"""Read-only dataset library, preview, CSV export, and manifest services."""

import csv
import io
import math
from collections.abc import Iterator
from datetime import date

from fastapi import HTTPException
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Admission, BedAssignment, BedTransfer, Department, Discharge, GenerationRun,
    Hospital, OccupancySnapshot, SyntheticPatient, ValidationReport,
)
from app.services.analytics import get_run_snapshot_summary
from app.schemas import (
    DatasetDepartmentRead, DatasetListItem, DatasetRecordCounts,
    DatasetRunDetailRead, DatasetValidationSummary,
)

ENTITY_DEFINITIONS = {
    "patients": {
        "model": SyntheticPatient,
        "fields": ["id", "run_id", "workspace_id", "hospital_id", "synthetic_patient_id", "age_band", "created_at"],
        "labels": ["Record ID", "Generation Run ID", "Workspace ID", "Hospital ID", "Synthetic Patient ID", "Age Band", "Created At (UTC)"],
        "search": ["synthetic_patient_id", "age_band"],
        "order": [SyntheticPatient.id],
    },
    "admissions": {
        "model": Admission,
        "fields": ["id", "run_id", "workspace_id", "hospital_id", "patient_id", "department_id", "initial_bed_id", "admitted_at", "status"],
        "labels": ["Admission ID", "Generation Run ID", "Workspace ID", "Hospital ID", "Patient Record ID", "Department ID", "Initial Bed ID", "Admitted At (UTC)", "Status"],
        "search": ["status"],
        "order": [Admission.admitted_at, Admission.id],
    },
    "discharges": {
        "model": Discharge,
        "fields": ["id", "run_id", "workspace_id", "hospital_id", "admission_id", "discharged_at"],
        "labels": ["Discharge ID", "Generation Run ID", "Workspace ID", "Hospital ID", "Admission ID", "Discharged At (UTC)"],
        "search": [],
        "order": [Discharge.discharged_at, Discharge.id],
    },
    "bed_assignments": {
        "model": BedAssignment,
        "fields": ["id", "run_id", "workspace_id", "hospital_id", "admission_id", "department_id", "bed_id", "start_at", "end_at"],
        "labels": ["Assignment ID", "Generation Run ID", "Workspace ID", "Hospital ID", "Admission ID", "Department ID", "Bed ID", "Start At (UTC)", "End At (UTC)"],
        "search": [],
        "order": [BedAssignment.start_at, BedAssignment.id],
    },
    "bed_transfers": {
        "model": BedTransfer,
        "fields": ["id", "run_id", "workspace_id", "hospital_id", "admission_id", "sequence_number", "source_department_id", "destination_department_id", "source_bed_id", "destination_bed_id", "transferred_at"],
        "labels": ["Transfer ID", "Generation Run ID", "Workspace ID", "Hospital ID", "Admission ID", "Sequence", "Source Department ID", "Destination Department ID", "Source Bed ID", "Destination Bed ID", "Transferred At (UTC)"],
        "search": [],
        "order": [BedTransfer.transferred_at, BedTransfer.sequence_number, BedTransfer.id],
    },
    "occupancy_snapshots": {
        "model": OccupancySnapshot,
        "fields": ["id", "run_id", "workspace_id", "hospital_id", "department_id", "snapshot_at", "operational_beds", "occupied_beds", "available_beds", "occupancy_pct"],
        "labels": ["Snapshot ID", "Generation Run ID", "Workspace ID", "Hospital ID", "Department ID", "Snapshot At (UTC)", "Operational Beds", "Occupied Beds", "Available Beds", "Occupancy (%)"],
        "search": [],
        "order": [OccupancySnapshot.snapshot_at, OccupancySnapshot.department_id, OccupancySnapshot.id],
    },
}


def _run_or_404(db: Session, run_id: str) -> GenerationRun:
    run = db.scalar(select(GenerationRun).where(GenerationRun.run_id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Generation run not found.")
    return run


def _request_config(run: GenerationRun) -> dict:
    return (run.config or {}).get("request", {}) or {}


def _parse_config_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _record_counts(db: Session, runs: list[GenerationRun], workspace_id: int | None = None) -> dict[str, DatasetRecordCounts]:
    counts = {run.run_id: {key: 0 for key in ENTITY_DEFINITIONS} for run in runs}
    if not runs:
        return {}
    run_hospitals = {run.run_id: run.hospital_id for run in runs}
    workspace_ids = {run.workspace_id for run in runs}
    if workspace_id is not None:
        workspace_ids = {workspace_id}
    for entity, definition in ENTITY_DEFINITIONS.items():
        model = definition["model"]
        rows = db.execute(
            select(model.run_id, model.hospital_id, func.count(model.id))
            .where(model.run_id.in_(run_hospitals), model.workspace_id.in_(workspace_ids))
            .group_by(model.run_id, model.hospital_id)
        )
        for run_id, hospital_id, total in rows:
            if run_hospitals.get(run_id) == hospital_id:
                counts[run_id][entity] = int(total)
    return {run_id: DatasetRecordCounts(**values) for run_id, values in counts.items()}


def _validation_summaries(db: Session, runs: list[GenerationRun]) -> dict[str, list[DatasetValidationSummary]]:
    if not runs:
        return {}
    by_id = {run.run_id: run for run in runs}
    reports = db.scalars(
        select(ValidationReport)
        .where(ValidationReport.run_id.in_(by_id))
        .order_by(ValidationReport.validated_at.desc(), ValidationReport.validation_id.desc())
    ).all()
    result: dict[str, list[DatasetValidationSummary]] = {run_id: [] for run_id in by_id}
    for report in reports:
        run = by_id.get(report.run_id)
        if run and report.workspace_id == run.workspace_id and report.hospital_id == run.hospital_id:
            result[report.run_id].append(DatasetValidationSummary(
                validation_id=report.validation_id,
                validated_at=report.validated_at,
                score=report.score,
                status=report.status,
                checks_performed=report.checks_performed,
                checks_passed=report.checks_passed,
                checks_failed=report.checks_failed,
            ))
    return result


def _list_item(run: GenerationRun, hospital_name: str, counts: DatasetRecordCounts,
               validations: list[DatasetValidationSummary]) -> DatasetListItem:
    config = run.config or {}
    request = _request_config(run)
    return DatasetListItem(
        run_id=run.run_id,
        workspace_id=run.workspace_id,
        hospital_id=run.hospital_id,
        hospital_name=hospital_name,
        started_at=run.started_at,
        completed_at=run.completed_at,
        status=run.status,
        seed=run.seed,
        configured_start_date=_parse_config_date(request.get("start_date")),
        configured_end_date=_parse_config_date(request.get("end_date")),
        target_occupancy_pct=request.get("target_occupancy_pct"),
        generator_version=config.get("generator_version"),
        record_counts=counts,
        latest_validation=validations[0] if validations else None,
    )


def list_datasets(db: Session, workspace_id: int, *, page: int, page_size: int,
                  q: str | None, hospital_id: int | None, status: str | None, sort: str) -> dict:
    from app.models import Workspace

    if db.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    query = select(GenerationRun, Hospital.name).join(Hospital, Hospital.id == GenerationRun.hospital_id).where(
        GenerationRun.workspace_id == workspace_id,
        Hospital.workspace_id == workspace_id,
    )
    if hospital_id is not None:
        query = query.where(GenerationRun.hospital_id == hospital_id)
    if status is not None:
        query = query.where(GenerationRun.status == status)
    if q:
        needle = f"%{q.strip()}%"
        query = query.where(or_(GenerationRun.run_id.ilike(needle), Hospital.name.ilike(needle)))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order = GenerationRun.started_at.asc() if sort == "oldest" else GenerationRun.started_at.desc()
    pairs = list(db.execute(query.order_by(order, GenerationRun.run_id).offset((page - 1) * page_size).limit(page_size)))
    runs = [run for run, _name in pairs]
    counts = _record_counts(db, runs, workspace_id)
    validations = _validation_summaries(db, runs)
    items = [
        _list_item(run, name, counts[run.run_id], validations.get(run.run_id, []))
        for run, name in pairs
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": math.ceil(total / page_size) if total else 0}


def get_dataset_detail(db: Session, run_id: str) -> DatasetRunDetailRead:
    run = _run_or_404(db, run_id)
    hospital = db.scalar(select(Hospital).where(
        Hospital.id == run.hospital_id,
        Hospital.workspace_id == run.workspace_id,
    ))
    if hospital is None:
        raise HTTPException(status_code=404, detail="Hospital not found for this generation run.")
    counts = _record_counts(db, [run])[run.run_id]
    validations = _validation_summaries(db, [run]).get(run.run_id, [])
    resolved = (run.config or {}).get("resolved_department_ids", [])
    departments = []
    if resolved:
        departments = [DatasetDepartmentRead(department_id=row.id, code=row.code, name=row.name)
                       for row in db.scalars(select(Department).where(
                           Department.id.in_(resolved), Department.hospital_id == run.hospital_id,
                       ).order_by(Department.name, Department.id)).all()]
    item = _list_item(run, hospital.name, counts, validations)
    return DatasetRunDetailRead(
        **item.model_dump(),
        generation_config=run.config or {},
        selected_departments=departments,
        validation_reports=validations,
        analytics_summary=get_run_snapshot_summary(db, run),
    )


def _entity_or_422(entity: str) -> dict:
    definition = ENTITY_DEFINITIONS.get(entity)
    if definition is None:
        choices = ", ".join(ENTITY_DEFINITIONS)
        raise HTTPException(status_code=422, detail=f"Invalid dataset entity. Choose one of: {choices}.")
    return definition


def _scoped_entity_query(run: GenerationRun, entity: str, q: str | None = None):
    definition = _entity_or_422(entity)
    model = definition["model"]
    query = select(model).where(
        model.run_id == run.run_id,
        model.workspace_id == run.workspace_id,
        model.hospital_id == run.hospital_id,
    )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        search = [cast(model.id, String).ilike(pattern)]
        search.extend(getattr(model, field).ilike(pattern) for field in definition["search"])
        query = query.where(or_(*search))
    return definition, query


def preview_dataset_entity(db: Session, run_id: str, entity: str, *, page: int,
                           page_size: int, q: str | None) -> dict:
    run = _run_or_404(db, run_id)
    definition, query = _scoped_entity_query(run, entity, q)
    model = definition["model"]
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = db.scalars(query.order_by(*definition["order"]).offset((page - 1) * page_size).limit(page_size)).all()
    fields = definition["fields"]
    items = [{field: getattr(row, field) for field in fields} for row in rows]
    return {
        "run_id": run.run_id,
        "entity": entity,
        "columns": [{"key": key, "label": label} for key, label in zip(fields, definition["labels"])],
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


def stream_entity_csv(db: Session, run_id: str, entity: str) -> Iterator[str]:
    run = _run_or_404(db, run_id)
    definition, query = _scoped_entity_query(run, entity)
    return _iter_entity_csv(db, query, definition)


def _iter_entity_csv(db: Session, query, definition: dict) -> Iterator[str]:
    model = definition["model"]
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(definition["fields"])
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)

    rows = db.scalars(query.order_by(*definition["order"]).execution_options(stream_results=True)).yield_per(500)
    for row in rows:
        writer.writerow([_csv_value(getattr(row, field)) for field in definition["fields"]])
        if buffer.tell() >= 65536:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
    if buffer.tell():
        yield buffer.getvalue()


def _csv_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def dataset_manifest(db: Session, run_id: str) -> dict:
    detail = get_dataset_detail(db, run_id)
    run = _run_or_404(db, run_id)
    config = run.config or {}
    request = _request_config(run)
    has_generator_version = bool(config.get("generator_version"))
    schema_version = config.get("schema_version")
    reasons = []
    if run.status != "completed":
        reasons.append("The generation run did not complete successfully.")
    if not has_generator_version:
        reasons.append("The run does not record a generator version.")
    if not schema_version:
        reasons.append("The run does not record a dataset schema version.")
    return {
        "application": {"name": "BedSynth AI"},
        "dataset_id": run.run_id,
        "generation_run_id": run.run_id,
        "workspace_id": run.workspace_id,
        "hospital": {"hospital_id": run.hospital_id, "hospital_name": detail.hospital_name},
        "generation": {
            "status": run.status,
            "created_at": run.started_at,
            "completed_at": run.completed_at,
            "configured_start_date": request.get("start_date"),
            "configured_end_date": request.get("end_date"),
            "seed": run.seed,
            "target_occupancy_pct": request.get("target_occupancy_pct"),
            "selected_departments": [department.model_dump() for department in detail.selected_departments],
            "configuration": config,
        },
        "versions": {
            "generator": config.get("generator_version"),
            "schema": schema_version,
            "application_at_generation": config.get("application_version"),
        },
        "record_counts": detail.record_counts.model_dump(),
        "validation_reports": [report.model_dump(mode="json") for report in detail.validation_reports],
        "reproducibility": {
            "reproducible": not reasons,
            "reason": None if not reasons else " ".join(reasons),
        },
    }
