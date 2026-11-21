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
    Hospital, OccupancySnapshot, SyntheticPatient, ValidationReport, WaitingQueueEntry, BedTurnaround,
)
from app.services.analytics import get_run_snapshot_summary, scenario_name_for_run
from app.schemas import (
    DatasetDepartmentRead, DatasetListItem, DatasetRecordCounts,
    DatasetRunDetailRead, DatasetValidationSummary,
)

ENTITY_DEFINITIONS = {
    "patients": {
        "model": SyntheticPatient,
        "fields": ["id", "run_id", "workspace_id", "hospital_id", "synthetic_patient_id", "age_band", "age_years", "gender", "created_at"],
        "labels": ["Record ID", "Generation Run ID", "Workspace ID", "Hospital ID", "Synthetic Patient ID", "Legacy Age Band", "Age (years)", "Gender", "Created At (UTC)"],
        "search": ["synthetic_patient_id", "age_band"],
        "order": [SyntheticPatient.id],
    },
    "admissions": {
        "model": Admission,
        "fields": ["id", "run_id", "workspace_id", "hospital_id", "patient_id", "department_id", "initial_bed_id", "admitted_at", "status", "admission_type", "requested_at", "scheduled_at", "bed_assigned_at"],
        "labels": ["Admission ID", "Generation Run ID", "Workspace ID", "Hospital ID", "Patient Record ID", "Department ID", "Initial Bed ID", "Admitted At (UTC)", "Status", "Admission Type", "Requested At (UTC)", "Scheduled At (UTC)", "Bed Assigned At (UTC)"],
        "search": ["status", "admission_type"],
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
    "waiting_queue": {
        "model": WaitingQueueEntry,
        "fields": ["id", "run_id", "workspace_id", "hospital_id", "request_number", "patient_id", "department_id", "admission_id", "requested_at", "priority", "status", "bed_assigned_at", "waiting_duration_seconds", "outcome_reason"],
        "labels": ["Queue Entry ID", "Generation Run ID", "Workspace ID", "Hospital ID", "Request Number", "Patient Record ID", "Department ID", "Admission ID", "Requested At (UTC)", "Priority", "Status", "Bed Assigned At (UTC)", "Waiting Duration (seconds)", "Outcome Reason"],
        "search": ["priority", "status", "outcome_reason"],
        "order": [WaitingQueueEntry.requested_at, WaitingQueueEntry.request_number],
    },
    "bed_turnaround": {
        "model": BedTurnaround,
        "fields": ["id", "run_id", "workspace_id", "hospital_id", "assignment_id", "admission_id", "bed_id", "department_id", "started_at", "completed_at", "duration_seconds"],
        "labels": ["Turnaround ID", "Generation Run ID", "Workspace ID", "Hospital ID", "Assignment ID", "Admission ID", "Bed ID", "Department ID", "Cleaning Started At (UTC)", "Cleaning Completed At (UTC)", "Turnaround Duration (seconds)"],
        "search": [],
        "order": [BedTurnaround.started_at, BedTurnaround.id],
    },
}

DATASET_SCHEMA_VERSION = "1.3.0"
BED_INVENTORY_FIELDS = [
    "run_id", "hospital_id", "bed_id", "bed_code", "department_id", "department_name",
    "bed_category", "bed_status", "generation_pool_member",
]


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
    for run in runs:
        counts[run.run_id]["waiting_queue"] = run.waiting_queue_count
        counts[run.run_id]["bed_turnaround"] = run.bed_turnaround_count
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
        scenario_name=scenario_name_for_run(run),
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
        choices = ", ".join((*ENTITY_DEFINITIONS, "bed_inventory"))
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
    if entity == "waiting_queue" and run.waiting_queue_count is None or entity == "bed_turnaround" and run.bed_turnaround_count is None:
        raise HTTPException(status_code=409, detail=f"{entity.replace('_', ' ').title()} data is unavailable for this historical run.")
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
    if entity == "waiting_queue" and run.waiting_queue_count is None or entity == "bed_turnaround" and run.bed_turnaround_count is None:
        raise HTTPException(status_code=409, detail=f"{entity.replace('_', ' ').title()} data is unavailable for this historical run.")
    definition, query = _scoped_entity_query(run, entity)
    return _iter_entity_csv(db, query, definition)


def _run_bed_inventory(run: GenerationRun) -> list[dict] | None:
    """Return the immutable generation-time bed snapshot, or None if it is legacy-unavailable."""
    config = run.config or {}
    if "resolved_bed_inventory" not in config:
        return None
    inventory = config.get("resolved_bed_inventory")
    if not isinstance(inventory, list):
        raise HTTPException(status_code=409, detail="The run's saved bed inventory metadata is invalid.")
    department_ids = set(config.get("resolved_department_ids") or [])
    for item in inventory:
        if not isinstance(item, dict) or item.get("hospital_id") != run.hospital_id or item.get("department_id") not in department_ids:
            raise HTTPException(status_code=409, detail="The run's saved bed inventory is outside its hospital or department scope.")
    return inventory


def stream_bed_inventory_csv(db: Session, run_id: str) -> Iterator[str]:
    run = _run_or_404(db, run_id)
    inventory = _run_bed_inventory(run)
    rows = [] if inventory is None else [
        {
            "run_id": run.run_id,
            "hospital_id": item["hospital_id"],
            "bed_id": item["bed_id"],
            "bed_code": item["bed_code"],
            "department_id": item["department_id"],
            "department_name": item["department_name"],
            "bed_category": item["bed_category"],
            "bed_status": item["bed_status"],
            "generation_pool_member": item["generation_pool_member"],
        }
        for item in inventory
    ]
    return _iter_rows_csv(BED_INVENTORY_FIELDS, rows)


def _iter_rows_csv(fields: list[str], rows: list[dict]) -> Iterator[str]:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\r\n", extrasaction="ignore")
    writer.writeheader()
    yield buffer.getvalue()
    for row in rows:
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow({field: _csv_value(row.get(field)) for field in fields})
        yield buffer.getvalue()


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
    generation_config_schema = config.get("schema_version")
    reasons = []
    if run.status != "completed":
        reasons.append("The generation run did not complete successfully.")
    if not has_generator_version:
        reasons.append("The run does not record a generator version.")
    if not generation_config_schema:
        reasons.append("The run does not record a generation configuration schema version.")
    inventory = _run_bed_inventory(run)
    record_counts = detail.record_counts.model_dump()
    record_counts["bed_inventory"] = None if inventory is None else len(inventory)
    configuration = dict(config)
    configuration.pop("resolved_bed_inventory", None)
    scenario = request.get("scenario")
    scenario_name = scenario_name_for_run(run)
    exported_files = [
        {"file": "patients.csv", "description": "Fictional patient demographics; primary key id joins to admissions.patient_id.", "record_count": record_counts["patients"], "status": "available"},
        {"file": "admissions.csv", "description": "Admission events; joins to patients by patient_id and to runs by run_id. admission_type is planned or emergency; requested_at is request time, scheduled_at is populated for planned admissions, admitted_at is the generated arrival/admission time, and bed_assigned_at records the first assignment time. Historical rows without these values remain null.", "record_count": record_counts["admissions"], "status": "available"},
        {"file": "discharges.csv", "description": "Discharge events; joins to admissions by admission_id. An admitted patient without a discharge row may be ongoing at the observation-window end; historical missing rows are not inferred.", "record_count": record_counts["discharges"], "status": "available"},
        {"file": "bed_assignments.csv", "description": "Bed assignment intervals; joins to admissions by admission_id, departments by department_id, and bed_inventory by bed_id when inventory metadata is available. A blank end_at denotes an ongoing assignment at the observation-window end when recorded by the generator.", "record_count": record_counts["bed_assignments"], "status": "available"},
        {"file": "bed_transfers.csv", "description": "Bed transfer events; joins to admissions by admission_id and identifies source and destination beds/departments.", "record_count": record_counts["bed_transfers"], "status": "available"},
        {"file": "occupancy_snapshots.csv", "description": "Department-level occupancy snapshots; joins to departments by department_id.", "record_count": record_counts["occupancy_snapshots"], "status": "available"},
        {"file": "waiting_queue.csv", "description": "One request outcome per synthetic patient request. Assigned entries link to admissions; unresolved or maximum-wait outcomes have a blank admission_id and assignment fields. Durations are elapsed seconds.", "record_count": record_counts["waiting_queue"], "status": "unavailable" if record_counts["waiting_queue"] is None else "available"},
        {"file": "bed_turnaround.csv", "description": "Cleaning/turnaround intervals linked to the closed bed assignment that vacated the bed. Intervals are half-open [started_at, completed_at); ongoing assignments have no turnaround row.", "record_count": record_counts["bed_turnaround"], "status": "unavailable" if record_counts["bed_turnaround"] is None else "available"},
        {
            "file": "bed_inventory.csv",
            "description": "Generation-time bed inventory for this run's selected hospital and departments. generation_pool_member marks beds eligible for the generator; non-operational beds remain in the inventory with their recorded status.",
            "record_count": record_counts["bed_inventory"],
            "status": "unavailable" if inventory is None else "empty" if not inventory else "available",
        },
    ]
    return {
        "application": {"name": "BedSynth AI"},
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
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
            "scenario": scenario,
            "scenario_name": scenario_name,
            "target_occupancy_pct": request.get("target_occupancy_pct"),
            "patient_profile": request.get("patient_profile"),
            "arrival_profile": request.get("arrival_profile"),
            "department_demand_weights": request.get("department_demand_weights"),
            "length_of_stay_profile": request.get("length_of_stay_profile"),
            "department_length_of_stay_profiles": request.get("department_length_of_stay_profiles"),
            "waiting_queue": request.get("waiting_queue"),
            "bed_turnaround_profile": request.get("bed_turnaround_profile"),
            "department_bed_turnaround_profiles": request.get("department_bed_turnaround_profiles"),
            "admission_arrival_policy": config.get("admission_arrival_policy"),
            "length_of_stay_policy": config.get("length_of_stay_policy"),
            "selected_departments": [department.model_dump() for department in detail.selected_departments],
            "configuration": configuration,
            "bed_inventory_metadata": {
                "available": inventory is not None,
                "record_count": None if inventory is None else len(inventory),
            },
        },
        "versions": {
            "generator": config.get("generator_version"),
            "schema": DATASET_SCHEMA_VERSION,
            "generation_config_schema": generation_config_schema,
            "application_at_generation": config.get("application_version"),
        },
        "record_counts": record_counts,
        "exported_files": exported_files,
        "timestamp_convention": {
            "timezone": "UTC",
            "format": "ISO 8601 date and datetime values",
            "serialization": "Values are serialized from stored timestamps without applying a time shift. SQLite may return naive datetime values; the generator constructs operation timestamps under its UTC policy.",
            "historical_data": "No existing timestamps are rewritten. Runs that predate explicit UTC metadata retain their stored values; consumers should not infer an offset that is not present in a value.",
        },
        "admission_timestamp_semantics": {
            "admission_type": "planned or emergency for runs generated with dataset schema 1.1.0; null means unavailable for a historical run and is not inferred",
            "requested_at": "Synthetic admission request instant, in UTC",
            "scheduled_at": "Planned arrival time; null for emergency admissions and unavailable for historical rows without the field",
            "admitted_at": "Generated hospital arrival/admission instant, in UTC",
            "bed_assigned_at": "First actual bed assignment instant, in UTC; it may occur after requested_at when a queue wait is simulated",
            "scenario_adjustment": "Emergency Surge applies a documented multiplier to the configured emergency-to-planned odds; the requested base proportions remain in generation.configuration.arrival_profile",
        },
        "length_of_stay_semantics": {
            "unit": "days",
            "distribution": "fixed uses the configured mode_days value; triangular uses minimum_days, mode_days, and maximum_days with seeded sampling",
            "department_profiles": "A configured profile applies only to its selected department; otherwise the global length_of_stay_profile applies",
            "seasonal_disease_surge": "The existing age-band factor is applied to the sampled stay and bounded by that selected profile's minimum_days and maximum_days",
            "discharge": "A discharge row is recorded only when the sampled discharge instant is within the configured observation window. Longer stays remain admitted with a null assignment end_at; this is right-censoring at the window boundary, not a fabricated discharge",
            "historical_data": "Missing historical discharge or assignment end timestamps remain unavailable and are not inferred",
        },
        "waiting_queue_semantics": {
            "request_timestamp": "For new runs, requested_at is the generated arrival/request instant for both admission types; planned scheduled_at records the same scheduled instant.",
            "wait_duration": "bed_assigned_at minus requested_at, measured in seconds; it is null unless a request is assigned.",
            "priority": "Configured emergency-first, planned-first, or arrival-order policy; request timestamp and stable request number break ties deterministically.",
            "outcomes": "assigned, waiting at observation-window end, or max_wait_exceeded. Unassigned requests do not create Admission rows because the existing Admission schema requires a bed.",
            "historical_data": "Runs without a saved waiting_queue_count have unavailable queue data; they are not treated as zero requests.",
        },
        "bed_turnaround_semantics": {
            "duration_unit": "seconds",
            "interval": "Half-open [started_at, completed_at); started_at equals the associated assignment end_at.",
            "patient_los": "Turnaround is separate from the patient's stay and does not shift discharge time.",
            "historical_data": "Runs without a saved bed_turnaround_count have unavailable turnaround data; no events are inferred.",
        },
        "relationships": [
            {"parent_file": "patients.csv", "parent_key": "id", "child_file": "admissions.csv", "child_key": "patient_id"},
            {"parent_file": "admissions.csv", "parent_key": "id", "child_file": "discharges.csv", "child_key": "admission_id"},
            {"parent_file": "admissions.csv", "parent_key": "id", "child_file": "bed_assignments.csv", "child_key": "admission_id"},
            {"parent_file": "admissions.csv", "parent_key": "id", "child_file": "bed_transfers.csv", "child_key": "admission_id"},
            {"parent_file": "admissions.csv", "parent_key": "id", "child_file": "waiting_queue.csv", "child_key": "admission_id", "note": "Blank admission_id denotes an unresolved request."},
            {"parent_file": "bed_assignments.csv", "parent_key": "id", "child_file": "bed_turnaround.csv", "child_key": "assignment_id"},
            {"parent_file": "generation.selected_departments", "parent_key": "department_id", "child_file": "occupancy_snapshots.csv", "child_key": "department_id"},
            {"parent_file": "generation_run_id", "parent_key": "run_id", "child_file": "all CSV exports", "child_key": "run_id"},
            {"parent_file": "bed_inventory.csv", "parent_key": "bed_id", "child_file": "bed_assignments.csv", "child_key": "bed_id", "availability": "Only when generation-time inventory metadata is available."},
        ],
        "null_semantics": {
            "meaning": "Null or empty fields mean the value was not recorded or is unavailable; they are not inferred defaults.",
            "historical_metadata": "Missing scenario, patient profile, length-of-stay profile, admission type, admission timestamps, waiting queue, turnaround, or bed inventory metadata is reported as unavailable. An empty inventory/event export is distinct from missing metadata. Historical events are not inferred.",
            "csv": "Nullable values serialize as empty CSV cells.",
        },
        "validation_reports": [report.model_dump(mode="json") for report in detail.validation_reports],
        "reproducibility": {
            "reproducible": not reasons,
            "reason": None if not reasons else " ".join(reasons),
        },
    }
