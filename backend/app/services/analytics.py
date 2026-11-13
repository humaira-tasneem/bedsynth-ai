"""Hospital-scoped analytics derived from one persisted generation run.

Independent runs are separate scenarios and may cover overlapping dates. The
service therefore selects the most recently completed run rather than blending
multiple runs into misleading hospital totals.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Admission, Bed, BedTransfer, Department, Discharge, GenerationRun, Hospital, OccupancySnapshot
from app.schemas import AnalyticsFilters


def _run_period(run: GenerationRun | None) -> tuple[date | None, date | None]:
    request = (run.config or {}).get("request", {}) if run else {}
    try:
        start = date.fromisoformat(request["start_date"]) if request.get("start_date") else None
        end = date.fromisoformat(request["end_date"]) if request.get("end_date") else None
        return start, end
    except (TypeError, ValueError):
        return None, None


def _context(db: Session, hospital_id: int, filters: AnalyticsFilters) -> dict:
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise HTTPException(status_code=404, detail="Hospital not found.")
    department = None
    if filters.department_id is not None:
        department = db.scalar(select(Department).where(
            Department.id == filters.department_id,
            Department.hospital_id == hospital_id,
        ))
        if department is None:
            raise HTTPException(status_code=404, detail="Department not found in this hospital.")

    run = db.scalar(select(GenerationRun).where(
        GenerationRun.hospital_id == hospital_id,
        GenerationRun.status == "completed",
    ).order_by(GenerationRun.completed_at.desc(), GenerationRun.started_at.desc()).limit(1))
    period_start, period_end = _run_period(run)
    start_date = filters.start_date or period_start
    end_date = filters.end_date or period_end
    if start_date is not None and end_date is not None:
        if end_date < start_date:
            raise HTTPException(status_code=422, detail="End date must be on or after start date.")
        if (end_date - start_date).days > 365:
            raise HTTPException(status_code=422, detail="Analytics date range cannot exceed 366 calendar days.")

    run_department_ids = (run.config or {}).get("resolved_department_ids", []) if run else []
    departments_query = select(Department).where(
        Department.hospital_id == hospital_id,
        Department.is_archived.is_(False),
    ).order_by(Department.name, Department.id)
    if run_department_ids:
        departments_query = departments_query.where(Department.id.in_(run_department_ids))
    if filters.department_id is not None:
        departments_query = departments_query.where(Department.id == filters.department_id)
    departments = list(db.scalars(departments_query).all())
    if run and run_department_ids and filters.department_id is not None and filters.department_id not in run_department_ids:
        raise HTTPException(status_code=422, detail="The selected department was not included in the latest completed generation run.")

    start_at = datetime.combine(start_date, time.min) if start_date else None
    end_before = datetime.combine(end_date + timedelta(days=1), time.min) if end_date else None
    metadata = {
        "hospital_id": hospital.id,
        "hospital_name": hospital.name,
        "run_id": run.run_id if run else None,
        "run_started_at": run.started_at if run else None,
        "seed": run.seed if run else None,
        "department_id": department.id if department else None,
        "department_name": department.name if department else None,
        "start_date": start_date,
        "end_date": end_date,
        "has_data": False,
    }
    return {
        "hospital": hospital, "run": run, "department": department,
        "departments": departments, "department_ids": [d.id for d in departments],
        "departments_expected": (1 if filters.department_id is not None else len(run_department_ids or [d.id for d in departments])),
        "start_date": start_date, "end_date": end_date,
        "start_at": start_at, "end_before": end_before,
        "metadata": metadata,
    }


def _with_period(query, column, context: dict):
    if context["start_at"] is not None:
        query = query.where(column >= context["start_at"])
    if context["end_before"] is not None:
        query = query.where(column < context["end_before"])
    return query


def _snapshots(db: Session, context: dict) -> list[OccupancySnapshot]:
    run = context["run"]
    if run is None or context["start_date"] is None or context["end_date"] is None:
        return []
    query = select(OccupancySnapshot).where(
        OccupancySnapshot.run_id == run.run_id,
        OccupancySnapshot.hospital_id == context["hospital"].id,
    )
    if context["department"] is not None:
        query = query.where(OccupancySnapshot.department_id == context["department"].id)
    return list(db.scalars(_with_period(query, OccupancySnapshot.snapshot_at, context)
                           .order_by(OccupancySnapshot.snapshot_at, OccupancySnapshot.id)).all())


def _daily_occupancy(snapshots: list[OccupancySnapshot]) -> tuple[list[dict], dict[tuple[date, int], OccupancySnapshot]]:
    # If a run contains more than one snapshot for a department on a UTC date,
    # daily charts use the latest timestamp from that day, never an interpolation.
    latest_by_dept_day: dict[tuple[date, int], OccupancySnapshot] = {}
    for snapshot in snapshots:
        latest_by_dept_day[(snapshot.snapshot_at.date(), snapshot.department_id)] = snapshot
    grouped: dict[date, list[OccupancySnapshot]] = defaultdict(list)
    for (day, _department_id), snapshot in latest_by_dept_day.items():
        grouped[day].append(snapshot)
    items = []
    for day in sorted(grouped):
        daily = grouped[day]
        operational = sum(row.operational_beds for row in daily)
        occupied = sum(row.occupied_beds for row in daily)
        available = sum(row.available_beds for row in daily)
        items.append({
            "date": day,
            "operational_beds": operational,
            "occupied_beds": occupied,
            "available_beds": available,
            "occupancy_pct": round(occupied / operational * 100, 2) if operational else None,
            "departments_reporting": len(daily),
            "snapshot_count": len(daily),
        })
    return items, latest_by_dept_day


def _events(db: Session, context: dict) -> tuple[dict[date, int], dict[date, int], dict[date, int]]:
    run = context["run"]
    if run is None or context["start_date"] is None or context["end_date"] is None:
        return {}, {}, {}
    hospital_id = context["hospital"].id
    department = context["department"]

    admissions_query = select(Admission.admitted_at).where(
        Admission.run_id == run.run_id, Admission.hospital_id == hospital_id,
    )
    if department:
        admissions_query = admissions_query.where(Admission.department_id == department.id)
    admissions = list(db.scalars(_with_period(admissions_query, Admission.admitted_at, context)).all())

    discharges_query = select(Discharge.discharged_at).join(
        Admission, Admission.id == Discharge.admission_id,
    ).where(Discharge.run_id == run.run_id, Discharge.hospital_id == hospital_id)
    if department:
        discharges_query = discharges_query.where(Admission.department_id == department.id)
    discharges = list(db.scalars(_with_period(discharges_query, Discharge.discharged_at, context)).all())

    transfers_query = select(BedTransfer.transferred_at).where(
        BedTransfer.run_id == run.run_id, BedTransfer.hospital_id == hospital_id,
    )
    if department:
        transfers_query = transfers_query.where(or_(
            BedTransfer.source_department_id == department.id,
            BedTransfer.destination_department_id == department.id,
        ))
    transfers = list(db.scalars(_with_period(transfers_query, BedTransfer.transferred_at, context)).all())

    def group_days(values):
        counts: dict[date, int] = defaultdict(int)
        for value in values:
            counts[value.date()] += 1
        return dict(counts)

    return group_days(admissions), group_days(discharges), group_days(transfers)


def _occupancy_stats(items: list[dict]) -> tuple[float | None, float | None]:
    values = [item["occupancy_pct"] for item in items if item["occupancy_pct"] is not None]
    if not values:
        return None, None
    return round(sum(values) / len(values), 2), round(max(values), 2)


def get_run_snapshot_summary(db: Session, run: GenerationRun) -> dict:
    """Summarize occupancy snapshots belonging only to this generation run."""
    snapshots = list(db.scalars(select(OccupancySnapshot).where(
        OccupancySnapshot.run_id == run.run_id,
        OccupancySnapshot.workspace_id == run.workspace_id,
        OccupancySnapshot.hospital_id == run.hospital_id,
    ).order_by(OccupancySnapshot.snapshot_at, OccupancySnapshot.id)).all())
    daily, _ = _daily_occupancy(snapshots)
    average, peak = _occupancy_stats(daily)
    latest = daily[-1] if daily else None
    return {
        "latest_snapshot_date": latest["date"] if latest else None,
        "latest_occupancy_pct": latest["occupancy_pct"] if latest else None,
        "average_occupancy_pct": average,
        "peak_occupancy_pct": peak,
        "occupied_beds_latest": latest["occupied_beds"] if latest else None,
        "available_beds_latest": latest["available_beds"] if latest else None,
        "recorded_days": len(daily),
    }


def get_overview(db: Session, hospital_id: int, filters: AnalyticsFilters) -> dict:
    context = _context(db, hospital_id, filters)
    snapshots = _snapshots(db, context)
    occupancy, _ = _daily_occupancy(snapshots)
    admission_days, discharge_days, transfer_days = _events(db, context)
    context["metadata"]["has_data"] = bool(snapshots or admission_days or discharge_days or transfer_days)
    average, peak = _occupancy_stats(occupancy)
    latest = occupancy[-1] if occupancy else None
    operational_query = select(Bed.id).join(Department, Department.id == Bed.department_id).where(
        Bed.hospital_id == hospital_id,
        Bed.status == "operational",
        Department.is_archived.is_(False),
    )
    if context["run"] and context["run"].config.get("resolved_department_ids"):
        operational_query = operational_query.where(Bed.department_id.in_(context["run"].config["resolved_department_ids"]))
    if context["department"]:
        operational_query = operational_query.where(Bed.department_id == context["department"].id)
    current_operational = len(db.scalars(operational_query).all())
    return {
        "metadata": context["metadata"],
        "metrics": {
            "operational_beds": current_operational,
            "occupied_beds_latest": latest["occupied_beds"] if latest else None,
            "available_beds_latest": latest["available_beds"] if latest else None,
            "latest_occupancy_pct": latest["occupancy_pct"] if latest else None,
            "latest_occupancy_date": latest["date"] if latest else None,
            "departments_reporting_latest": latest["departments_reporting"] if latest else 0,
            "departments_expected": context["departments_expected"],
            "average_occupancy_pct": average,
            "peak_occupancy_pct": peak,
            "admissions": sum(admission_days.values()),
            "discharges": sum(discharge_days.values()),
            "transfers": sum(transfer_days.values()),
            "occupancy_snapshots": len(snapshots),
        },
    }


def get_occupancy(db: Session, hospital_id: int, filters: AnalyticsFilters) -> dict:
    context = _context(db, hospital_id, filters)
    snapshots = _snapshots(db, context)
    items, _ = _daily_occupancy(snapshots)
    context["metadata"]["has_data"] = bool(snapshots)
    return {"metadata": context["metadata"], "items": items}


def get_patient_flow(db: Session, hospital_id: int, filters: AnalyticsFilters) -> dict:
    context = _context(db, hospital_id, filters)
    admission_days, discharge_days, transfer_days = _events(db, context)
    has_snapshot = bool(_snapshots(db, context))
    has_events = bool(admission_days or discharge_days or transfer_days)
    context["metadata"]["has_data"] = has_snapshot or has_events
    items = []
    if context["metadata"]["has_data"] and context["start_date"] is not None and context["end_date"] is not None:
        day = context["start_date"]
        while day <= context["end_date"]:
            items.append({
                "date": day,
                "admissions": admission_days.get(day, 0),
                "discharges": discharge_days.get(day, 0),
                "transfers": transfer_days.get(day, 0),
            })
            day += timedelta(days=1)
    return {"metadata": context["metadata"], "items": items}


def get_departments(db: Session, hospital_id: int, filters: AnalyticsFilters) -> dict:
    context = _context(db, hospital_id, filters)
    snapshots = _snapshots(db, context)
    occupancy, latest_by_dept_day = _daily_occupancy(snapshots)
    admission_days, discharge_days, transfer_days = _events(db, context)
    context["metadata"]["has_data"] = bool(snapshots or admission_days or discharge_days or transfer_days)

    snapshots_by_department: dict[int, list[tuple[date, OccupancySnapshot]]] = defaultdict(list)
    for (day, department_id), snapshot in latest_by_dept_day.items():
        snapshots_by_department[department_id].append((day, snapshot))
    operational_query = select(Bed.department_id, Bed.id).join(Department, Department.id == Bed.department_id).where(
        Bed.hospital_id == hospital_id,
        Bed.status == "operational",
        Department.is_archived.is_(False),
    )
    if context["run"] and context["run"].config.get("resolved_department_ids"):
        operational_query = operational_query.where(Bed.department_id.in_(context["run"].config["resolved_department_ids"]))
    operational_by_department: dict[int, int] = defaultdict(int)
    for department_id, _bed_id in db.execute(operational_query):
        operational_by_department[department_id] += 1

    results = []
    for department in context["departments"]:
        recorded = sorted(snapshots_by_department.get(department.id, []), key=lambda pair: pair[0])
        daily_percentages = [
            round(snapshot.occupied_beds / snapshot.operational_beds * 100, 2)
            for _day, snapshot in recorded if snapshot.operational_beds > 0
        ]
        latest_snapshot = recorded[-1][1] if recorded else None
        results.append({
            "department_id": department.id,
            "department_name": department.name,
            "department_code": department.code,
            "operational_beds": operational_by_department.get(department.id, 0),
            "occupied_beds_latest": latest_snapshot.occupied_beds if latest_snapshot else None,
            "available_beds_latest": latest_snapshot.available_beds if latest_snapshot else None,
            "latest_occupancy_pct": (round(latest_snapshot.occupied_beds / latest_snapshot.operational_beds * 100, 2)
                                     if latest_snapshot and latest_snapshot.operational_beds else None),
            "average_occupancy_pct": round(sum(daily_percentages) / len(daily_percentages), 2) if daily_percentages else None,
            "peak_occupancy_pct": max(daily_percentages) if daily_percentages else None,
            "snapshots": len(recorded),
        })
    return {"metadata": context["metadata"], "items": results}
