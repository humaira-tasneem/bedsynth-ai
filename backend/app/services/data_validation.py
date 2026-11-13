"""Read-only validation for persisted synthetic generation runs.

The validator never repairs or updates source records. Its only write is a
separate, immutable validation report and associated JSON detail.
"""

from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Admission, Bed, BedAssignment, BedTransfer, Department, Discharge,
    GenerationRun, Hospital, OccupancySnapshot, SyntheticPatient,
    ValidationReport,
)

CATEGORY_WEIGHTS = {
    "completeness": 10.0,
    "uniqueness": 10.0,
    "referential_integrity": 20.0,
    "temporal_validity": 15.0,
    "bed_assignment_consistency": 15.0,
    "capacity_consistency": 15.0,
    "occupancy_accuracy": 15.0,
}


def _as_id(value: object) -> str | int | None:
    return value if isinstance(value, (str, int)) else None


def evaluate_run(db: Session, run_id: str) -> dict:
    """Evaluate one run and return a JSON-safe report without mutating source rows."""
    run = db.get(GenerationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Generation run not found.")
    if run.status != "completed":
        raise HTTPException(status_code=409, detail="Only completed generation runs can be validated.")

    def rows(model):
        return list(db.scalars(select(model).where(model.run_id == run_id)).all())

    patients = rows(SyntheticPatient)
    admissions = rows(Admission)
    discharges = rows(Discharge)
    assignments = rows(BedAssignment)
    transfers = rows(BedTransfer)
    snapshots = rows(OccupancySnapshot)
    hospital = db.get(Hospital, run.hospital_id)
    patient_by_id = {row.id: row for row in patients}
    admission_by_id = {row.id: row for row in admissions}
    discharge_by_admission = {row.admission_id: row for row in discharges}
    departments = {row.id: row for row in db.scalars(select(Department).where(Department.hospital_id == run.hospital_id)).all()}
    beds = {row.id: row for row in db.scalars(select(Bed).where(Bed.hospital_id == run.hospital_id)).all()}

    checks: dict[str, list[dict]] = {name: [] for name in CATEGORY_WEIGHTS}
    issues: list[dict] = []

    def check(category: str, code: str, ok: bool, message: str, *, severity: str = "high", entity_type: str | None = None, entity_id=None):
        checks[category].append({"code": code, "passed": bool(ok)})
        if not ok:
            issues.append({"category": category, "severity": severity, "code": code, "message": message,
                           "entity_type": entity_type, "entity_id": _as_id(entity_id)})

    # Completeness: required record identifiers and expected record populations.
    check("completeness", "required_identifiers", all(x.id is not None for group in (patients, admissions, discharges, assignments, transfers, snapshots) for x in group)
          and all(x.synthetic_patient_id for x in patients), "One or more required record identifiers are missing.", severity="critical")
    check("completeness", "run_counts", len(patients) == run.patients_count and len(admissions) == run.admissions_count
          and len(discharges) == run.discharges_count and len(transfers) == run.transfers_count
          and len(snapshots) == run.snapshots_count, "Persisted record counts do not match the generation run metadata.", severity="medium", entity_type="generation_run", entity_id=run_id)

    # Uniqueness: database constraints are defense in depth; these checks also
    # detect legacy/corrupted imports that predate those constraints.
    synthetic_ids = [x.synthetic_patient_id for x in patients]
    check("uniqueness", "synthetic_patient_identifier", len(synthetic_ids) == len(set(synthetic_ids)),
          "Synthetic patient identifiers are duplicated within this run.", severity="critical")
    check("uniqueness", "admission_per_patient", len([x.patient_id for x in admissions]) == len(set(x.patient_id for x in admissions)),
          "A patient has more than one admission in this run.", severity="high")
    for code, rows_to_check, key in (
        ("discharge_per_admission", discharges, lambda x: x.admission_id),
        ("transfer_sequence", transfers, lambda x: (x.admission_id, x.sequence_number)),
        ("snapshot_department_time", snapshots, lambda x: (x.department_id, x.snapshot_at)),
    ):
        values = [key(row) for row in rows_to_check]
        check("uniqueness", code, len(values) == len(set(values)), f"Duplicate {code.replace('_', ' ')} values were found.", severity="high")

    # Referential integrity includes ownership scope, not only existence.
    scope_ok = bool(hospital and hospital.workspace_id == run.workspace_id)
    scope_ok = scope_ok and all(x.run_id == run_id and x.workspace_id == run.workspace_id and x.hospital_id == run.hospital_id for group in (patients, admissions, discharges, assignments, transfers, snapshots) for x in group)
    check("referential_integrity", "workspace_hospital_run_scope", scope_ok,
          "Run records do not consistently belong to the run's workspace and hospital.", severity="critical")
    patient_refs_ok = all(x.patient_id in patient_by_id for x in admissions)
    check("referential_integrity", "admission_patient", patient_refs_ok, "An admission references a missing patient in this run.", severity="critical")
    admission_refs_ok = all(x.admission_id in admission_by_id for group in (discharges, assignments, transfers) for x in group)
    check("referential_integrity", "operational_admission", admission_refs_ok, "An operational record references a missing admission in this run.", severity="critical")
    bed_refs_ok = all(x.bed_id in beds for x in assignments) and all(x.initial_bed_id in beds for x in admissions) and all(x.source_bed_id in beds and x.destination_bed_id in beds for x in transfers)
    check("referential_integrity", "hospital_bed", bed_refs_ok, "An admission, assignment, or transfer references a missing or foreign-hospital bed.", severity="critical")
    dept_refs_ok = all(x.department_id in departments for x in assignments) and all(x.department_id in departments for x in snapshots) and all(x.department_id in departments for x in admissions)
    check("referential_integrity", "hospital_department", dept_refs_ok, "An operational record references a missing or foreign-hospital department.", severity="critical")
    check("referential_integrity", "bed_department_ownership",
          all(x.bed_id not in beds or x.department_id not in departments or beds[x.bed_id].department_id == x.department_id for x in assignments)
          and all(x.initial_bed_id not in beds or beds[x.initial_bed_id].department_id == x.department_id for x in admissions),
          "A referenced bed does not belong to the record's department.", severity="critical")
    check("referential_integrity", "transfer_endpoints", all(
        (t.source_bed_id not in beds or beds[t.source_bed_id].department_id == t.source_department_id)
        and (t.destination_bed_id not in beds or beds[t.destination_bed_id].department_id == t.destination_department_id)
        and t.source_department_id in departments and t.destination_department_id in departments
        for t in transfers), "A transfer endpoint does not match its stated hospital department.", severity="critical")

    # Temporal records use naive UTC as persisted by the current generator;
    # comparisons are safe because all generator timestamps share that policy.
    temporal_ok = all(x.admitted_at is not None for x in admissions)
    for discharge in discharges:
        admission = admission_by_id.get(discharge.admission_id)
        temporal_ok = temporal_ok and bool(admission and discharge.discharged_at >= admission.admitted_at)
    for assignment in assignments:
        admission = admission_by_id.get(assignment.admission_id)
        temporal_ok = temporal_ok and bool(assignment.start_at is not None and (assignment.end_at is None or assignment.end_at > assignment.start_at))
        if admission:
            temporal_ok = temporal_ok and assignment.start_at >= admission.admitted_at
            discharge = discharge_by_admission.get(admission.id)
            if discharge:
                temporal_ok = temporal_ok and (assignment.end_at is None or assignment.end_at <= discharge.discharged_at)
    check("temporal_validity", "admission_discharge_order", temporal_ok,
          "Admission, assignment, or discharge timestamps are missing or out of order.", severity="critical")
    transfer_time_ok = all(
        t.admission_id not in admission_by_id or
        (admission_by_id[t.admission_id].admitted_at <= t.transferred_at and
         (t.admission_id not in discharge_by_admission or t.transferred_at <= discharge_by_admission[t.admission_id].discharged_at))
        for t in transfers)
    check("temporal_validity", "transfer_timestamp_order", transfer_time_ok,
          "A transfer occurs outside its admission and discharge interval.", severity="high")
    discharge_links_ok = all(
        (a.status == "discharged") == (a.id in discharge_by_admission)
        and (a.status != "admitted" or a.id in admission_by_id)
        for a in admissions
    )
    check("temporal_validity", "admission_discharge_record_link", discharge_links_ok,
          "Admission status and its discharge record do not agree.", severity="high")
    check("temporal_validity", "snapshot_timestamps", all(x.snapshot_at is not None for x in snapshots),
          "An occupancy snapshot has no timestamp.", severity="high")

    # Assignment intervals are half-open [start_at, end_at): an end exactly at
    # the next start is valid. Both patient and bed may have only one active
    # assignment at a point in time.
    intervals_ok = True
    current_beds_ok = True
    assignments_by_bed = defaultdict(list)
    assignments_by_admission = defaultdict(list)
    for row in assignments:
        assignments_by_bed[row.bed_id].append(row)
        assignments_by_admission[row.admission_id].append(row)
        bed = beds.get(row.bed_id)
        if bed and bed.status != "operational":
            current_beds_ok = False
    for group in (*assignments_by_bed.values(), *assignments_by_admission.values()):
        ordered = sorted(group, key=lambda x: x.start_at)
        for left, right in zip(ordered, ordered[1:]):
            if left.end_at is None or left.end_at > right.start_at:
                intervals_ok = False
    check("bed_assignment_consistency", "assignment_overlap", intervals_ok,
          "Bed assignments overlap for a bed or an admission.", severity="critical")
    check("bed_assignment_consistency", "assignment_bed_operational", current_beds_ok,
          "An assignment uses a bed that is currently not operational; historical bed-status changes are not versioned.", severity="low")
    initial_assignments_ok = all(any(a.admission_id == admission.id and a.bed_id == admission.initial_bed_id and a.start_at == admission.admitted_at for a in assignments) for admission in admissions)
    check("bed_assignment_consistency", "initial_assignment", initial_assignments_ok,
          "An admission does not begin with an assignment to its initial bed.", severity="high")

    transfer_ok = True
    by_admission_bed = defaultdict(list)
    for assignment in assignments:
        by_admission_bed[(assignment.admission_id, assignment.bed_id)].append(assignment)
    transfer_groups = defaultdict(list)
    for transfer in transfers:
        transfer_groups[transfer.admission_id].append(transfer)
        sources = by_admission_bed.get((transfer.admission_id, transfer.source_bed_id), [])
        destinations = by_admission_bed.get((transfer.admission_id, transfer.destination_bed_id), [])
        source_ok = any(a.start_at < transfer.transferred_at and a.end_at == transfer.transferred_at for a in sources)
        destination_ok = any(a.start_at == transfer.transferred_at for a in destinations)
        transfer_ok = transfer_ok and source_ok and destination_ok
    for group in transfer_groups.values():
        group.sort(key=lambda x: x.sequence_number)
        transfer_ok = transfer_ok and all(t.sequence_number == index for index, t in enumerate(group, start=1))
        transfer_ok = transfer_ok and all(a.transferred_at < b.transferred_at for a, b in zip(group, group[1:]))
    check("bed_assignment_consistency", "transfer_assignment_sequence", transfer_ok,
          "Transfer sequence does not match source and destination assignment intervals.", severity="critical")

    # Recalculate occupancy at each stored snapshot from interval membership.
    occupancy_ok = True
    zero_capacity_ok = True
    capacity_temporal_ok = True
    assignment_capacity_ok = True
    capacity_mismatch = False
    for snapshot in snapshots:
        dept_assignments = [a for a in assignments if a.department_id == snapshot.department_id]
        occupied = sum(1 for a in dept_assignments if a.start_at <= snapshot.snapshot_at and (a.end_at is None or snapshot.snapshot_at < a.end_at))
        expected_available = snapshot.operational_beds - occupied
        expected_pct = (occupied / snapshot.operational_beds * 100) if snapshot.operational_beds else None
        occupancy_ok = occupancy_ok and snapshot.occupied_beds == occupied and snapshot.available_beds == expected_available
        if expected_pct is None:
            zero_capacity_ok = zero_capacity_ok and snapshot.occupancy_pct is None
        else:
            zero_capacity_ok = zero_capacity_ok and snapshot.occupancy_pct is not None and abs(snapshot.occupancy_pct - expected_pct) < 0.011
        if occupied > snapshot.operational_beds or snapshot.operational_beds < 0 or snapshot.available_beds < 0:
            capacity_temporal_ok = False
        live_operational = sum(1 for bed in beds.values() if bed.department_id == snapshot.department_id and bed.status == "operational")
        if live_operational != snapshot.operational_beds:
            capacity_mismatch = True
    # Check every assignment boundary as well as snapshots so short-lived
    # occupancy peaks cannot be hidden between snapshot times.
    for department_id in departments:
        dept_rows = [a for a in assignments if a.department_id == department_id]
        boundaries = {a.start_at for a in dept_rows}
        boundaries.update(a.end_at for a in dept_rows if a.end_at is not None)
        operational_capacity = sum(1 for b in beds.values() if b.department_id == department_id and b.status == "operational")
        for at in boundaries:
            active = sum(1 for a in dept_rows if a.start_at <= at and (a.end_at is None or at < a.end_at))
            if active > operational_capacity:
                assignment_capacity_ok = False
    check("occupancy_accuracy", "snapshot_from_assignments", occupancy_ok,
          "Stored occupancy or availability differs from assignment intervals.", severity="critical")
    check("occupancy_accuracy", "occupancy_percentage", zero_capacity_ok,
          "Occupancy percentage does not match the ratio, or zero-capacity occupancy is not null.", severity="high")
    check("capacity_consistency", "snapshot_capacity_bounds", capacity_temporal_ok,
          "A snapshot exceeds its operational bed count or has negative capacity/availability.", severity="critical")
    check("capacity_consistency", "assignment_capacity_over_time", assignment_capacity_ok,
          "Active bed assignments exceed current operational bed capacity at an event boundary.", severity="critical")
    check("capacity_consistency", "configured_department_capacity", all(
        department.bed_capacity is None or sum(1 for b in beds.values() if b.department_id == department.id and b.status != "retired") <= department.bed_capacity
        for department in departments.values()), "Current non-retired inventory exceeds configured department capacity.", severity="high")
    check("capacity_consistency", "operational_inventory_at_validation", not capacity_mismatch,
          "Current operational inventory differs from a run snapshot; the application does not retain historical bed-status intervals.", severity="low")

    category_results = []
    total_checks = total_passed = 0
    weighted_score = 0.0
    for category, weight in CATEGORY_WEIGHTS.items():
        category_checks = checks[category]
        passed = sum(item["passed"] for item in category_checks)
        count = len(category_checks)
        score = passed / count * 100 if count else 100.0
        weighted_score += weight * score / 100
        total_checks += count
        total_passed += passed
        category_results.append({"category": category, "weight": weight, "checks_performed": count,
                                 "checks_passed": passed, "checks_failed": count - passed,
                                 "issue_count": sum(1 for issue in issues if issue["category"] == category), "score": round(score, 2)})
    has_critical = any(issue["severity"] == "critical" for issue in issues)
    score = min(weighted_score, 49.0) if has_critical else weighted_score
    warning_count = sum(1 for issue in issues if issue["severity"] != "critical")
    status = "failed" if has_critical else ("passed_with_warnings" if issues else "passed")
    return {
        "validation_id": str(uuid4()), "run_id": run.run_id, "workspace_id": run.workspace_id,
        "hospital_id": run.hospital_id, "validated_at": datetime.now(timezone.utc), "score": round(score, 2),
        "checks_performed": total_checks, "checks_passed": total_passed,
        "checks_failed": total_checks - total_passed, "warning_count": warning_count,
        "status": status, "categories": category_results, "issues": issues,
    }


def persist_validation(db: Session, run_id: str) -> ValidationReport:
    """Evaluate a completed run and persist only the report, never source data."""
    result = evaluate_run(db, run_id)
    report = ValidationReport(**result)
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
