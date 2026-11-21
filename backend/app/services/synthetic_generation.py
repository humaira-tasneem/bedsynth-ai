"""Deterministic synthetic hospital operations generation service."""

from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import datetime, time, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Admission,
    Bed,
    BedAssignment,
    BedTransfer,
    BedTurnaround,
    Department,
    Discharge,
    GenerationRun,
    Hospital,
    OccupancySnapshot,
    SyntheticPatient,
    WaitingQueueEntry,
    utc_now,
)
from app.schemas import (
    DepartmentLengthOfStayProfile,
    GenerationConfig,
    GenerationCreate,
    GenerationPreviewRead,
    LengthOfStayProfile,
    PatientProfileConfig,
    BedTurnaroundProfile,
)

GENERATOR_VERSION = "deterministic-6"
AGE_BANDS = ("0-17", "18-34", "35-49", "50-64", "65-79", "80+")
PROFILE_AGE_GROUPS = (
    ("children_0_17", 0, 17),
    ("young_adults_18_35", 18, 35),
    ("middle_aged_adults_36_59", 36, 59),
    ("older_adults_60_79", 60, 79),
    ("elderly_80_plus", 80, 120),
)
TRANSFER_POLICY = {
    "name": "seeded-eligible-sample-v1",
    "minimum_stay_hours": 4,
    "seeded_selection": "one in five eligible admissions",
    "destination": "a distinct operational bed unused by the concurrent cohort",
}
SCENARIO_PRESETS: dict[str, dict[str, Any]] = {
    "normal_operations": {
        "name": "Normal Operations", "admission_volume_factor": 1.0, "peak_pressure_factor": 1.0,
        "department_bias": {}, "transfer_selection": "one in five eligible admissions",
    },
    "high_patient_inflow": {
        "name": "High Patient Inflow", "admission_volume_factor": 1.2, "peak_pressure_factor": 1.15,
        "department_bias": {"emergency": 1.8, "general": 1.35},
        "transfer_selection": "one in five eligible admissions",
    },
    "seasonal_disease_surge": {
        "name": "Seasonal Disease Surge", "admission_volume_factor": 1.15, "peak_pressure_factor": 1.1,
        "department_bias": {"emergency": 1.5, "general": 1.4, "respiratory": 1.8, "pediatric": 1.35},
        "transfer_selection": "one in five eligible admissions",
    },
    "emergency_surge": {
        "name": "Emergency Surge", "admission_volume_factor": 1.25, "peak_pressure_factor": 1.25,
        "department_bias": {"emergency": 2.5},
        "emergency_odds_multiplier": 2.0,
        "arrival_profile": "individually timed arrivals with an increased emergency share",
        "transfer_selection": "one in two eligible admissions",
    },
    "low_occupancy": {
        "name": "Low Occupancy", "admission_volume_factor": 0.7, "peak_pressure_factor": 0.65,
        "department_bias": {}, "transfer_selection": "one in five eligible admissions",
    },
}


def _scenario_admission_count(config: GenerationConfig) -> int:
    if not config.target_admissions:
        return 0
    factor = SCENARIO_PRESETS[config.scenario]["admission_volume_factor"]
    return min(5000, math.ceil(config.target_admissions * factor))


def _scenario_peak(config: GenerationConfig, total_beds: int) -> int:
    admission_count = _scenario_admission_count(config)
    if not admission_count:
        return 0
    preset = SCENARIO_PRESETS[config.scenario]
    baseline = math.ceil(total_beds * config.target_occupancy_pct / 100)
    adjusted = math.ceil(baseline * preset["peak_pressure_factor"])
    return min(total_beds, admission_count, adjusted)


def _effective_admission_mix(config: GenerationConfig) -> dict[str, int]:
    profile = config.arrival_profile
    planned_weight = float(profile.planned_pct)
    emergency_weight = float(profile.emergency_pct) * SCENARIO_PRESETS[config.scenario].get("emergency_odds_multiplier", 1.0)
    denominator = planned_weight + emergency_weight
    if denominator == 0:
        return {"planned": 0, "emergency": 0}
    emergency_pct = round(emergency_weight / denominator * 100)
    return {"planned": 100 - emergency_pct, "emergency": emergency_pct}


def _scenario_bed_order(beds: list[Bed], departments: list[Department], config: GenerationConfig, rng: random.Random) -> list[Bed]:
    preset = SCENARIO_PRESETS[config.scenario]
    configured_weights = {row.department_id: row.weight for row in config.department_demand_weights}
    if not preset["department_bias"] and not configured_weights:
        result = beds.copy()
        rng.shuffle(result)
        return result
    names = {department.id: department.name.casefold() for department in departments}
    biases = preset["department_bias"]
    # Order departments by their explicit scenario priority, randomizing beds
    # within each group while keeping every operational bed unique.
    grouped: dict[float, list[Bed]] = {}
    for bed in beds:
        weight = configured_weights.get(bed.department_id, max(
            [factor for keyword, factor in biases.items() if keyword in names.get(bed.department_id, "")]
            or [1.0]
        ))
        grouped.setdefault(weight, []).append(bed)
    result = []
    for weight in sorted(grouped, reverse=True):
        rng.shuffle(grouped[weight])
        result.extend(grouped[weight])
    return result


def _profiled_hour_weight(value: datetime, config: GenerationConfig) -> float:
    hour = value.hour
    time_profile = config.arrival_profile.time_of_day
    if time_profile == "daytime":
        hour_weight = 2.0 if 7 <= hour < 19 else 0.5
    elif time_profile == "evening":
        hour_weight = 2.0 if 16 <= hour < 24 else 0.5
    elif time_profile == "overnight":
        hour_weight = 2.0 if 0 <= hour < 7 else 0.5
    else:
        hour_weight = 1.0

    weekday = value.weekday() < 5
    day_profile = config.arrival_profile.day_of_week
    if day_profile == "weekdays":
        day_weight = 1.5 if weekday else 0.5
    elif day_profile == "weekends":
        day_weight = 0.5 if weekday else 1.5
    else:
        day_weight = 1.0
    return hour_weight * day_weight


def _generate_arrival_timestamps(config: GenerationConfig, admission_types: list[str]) -> list[datetime]:
    """Sample deterministic, individually jittered UTC arrivals from configured calendar weights."""
    if not admission_types:
        return []
    start_at = datetime.combine(config.start_date, time.min, tzinfo=timezone.utc).replace(tzinfo=None)
    end_exclusive = datetime.combine(config.end_date + timedelta(days=1), time.min, tzinfo=timezone.utc).replace(tzinfo=None)
    last_valid = end_exclusive - timedelta(seconds=2)
    hour_starts: list[datetime] = []
    cursor = start_at
    while cursor <= last_valid:
        hour_starts.append(cursor)
        cursor += timedelta(hours=1)
    rng = random.Random(f"bedsynth-arrivals-v2:{config.seed}")
    chosen: set[datetime] = set()
    arrivals: list[datetime] = []
    surge_cutoff = start_at + (last_valid - start_at) * 0.2
    for admission_type in admission_types:
        while True:
            candidate = _sample_weighted_arrival(config, admission_type, rng, hour_starts, end_exclusive, surge_cutoff)
            if candidate <= last_valid and candidate not in chosen:
                chosen.add(candidate)
                arrivals.append(candidate)
                break
    return arrivals


def _sample_weighted_arrival(
    config: GenerationConfig,
    admission_type: str,
    rng: random.Random,
    hour_starts: list[datetime] | None = None,
    end_exclusive: datetime | None = None,
    surge_cutoff: datetime | None = None,
) -> datetime:
    start_at = datetime.combine(config.start_date, time.min, tzinfo=timezone.utc).replace(tzinfo=None)
    end_exclusive = end_exclusive or datetime.combine(config.end_date + timedelta(days=1), time.min, tzinfo=timezone.utc).replace(tzinfo=None)
    if hour_starts is None:
        hour_starts = []
        cursor = start_at
        while cursor < end_exclusive:
            hour_starts.append(cursor)
            cursor += timedelta(hours=1)
    if surge_cutoff is None:
        surge_cutoff = start_at + (end_exclusive - timedelta(seconds=2) - start_at) * 0.2
    weights = []
    for hour in hour_starts:
        base_weight = _profiled_hour_weight(hour, config)
        if config.scenario == "emergency_surge" and admission_type == "emergency":
            base_weight *= 4.0 if hour <= surge_cutoff else 0.25
        weights.append(base_weight)
    hour = rng.choices(hour_starts, weights=weights, k=1)[0]
    slot_end = min(hour + timedelta(hours=1), end_exclusive) - timedelta(seconds=1)
    available_seconds = int((slot_end - hour).total_seconds())
    return hour + timedelta(seconds=rng.randint(0, max(0, available_seconds)))


def _generate_admission_types(config: GenerationConfig, count: int) -> list[str]:
    mix = _effective_admission_mix(config)
    allocated = _allocate_category_counts(count, [mix["planned"], mix["emergency"]])
    values = ["planned"] * allocated[0] + ["emergency"] * allocated[1]
    random.Random(f"bedsynth-admission-types-v1:{config.seed}").shuffle(values)
    return values


def _allocate_category_counts(count: int, percentages: list[int]) -> list[int]:
    """Allocate whole records by largest remainder, preserving requested shares as closely as possible."""
    exact = [count * percentage / 100 for percentage in percentages]
    allocated = [math.floor(value) for value in exact]
    remainder = count - sum(allocated)
    priority = sorted(range(len(percentages)), key=lambda index: (exact[index] - allocated[index], -index), reverse=True)
    for index in priority[:remainder]:
        allocated[index] += 1
    return allocated


def _legacy_age_band(age_years: int) -> str:
    if age_years < 18:
        return "0-17"
    if age_years < 35:
        return "18-34"
    if age_years < 50:
        return "35-49"
    if age_years < 65:
        return "50-64"
    if age_years < 80:
        return "65-79"
    return "80+"


def _generate_patient_demographics(count: int, profile: PatientProfileConfig, seed: int) -> list[tuple[int, str]]:
    """Build a deterministic, near-exact demographic mix without changing scenario demand settings."""
    rng = random.Random(f"bedsynth-patient-profile-v1:{seed}")
    age_distribution = profile.age_distribution.model_dump()
    age_percentages = [age_distribution[name] for name, _, _ in PROFILE_AGE_GROUPS]
    age_counts = _allocate_category_counts(count, age_percentages)
    ages: list[int] = []
    for (_, group_min, group_max), group_count in zip(PROFILE_AGE_GROUPS, age_counts, strict=True):
        lower = max(group_min, profile.minimum_age)
        upper = min(group_max, profile.maximum_age)
        ages.extend(rng.randint(lower, upper) for _ in range(group_count))
    rng.shuffle(ages)

    gender_distribution = profile.gender_distribution.model_dump()
    gender_names = list(gender_distribution)
    gender_percentages = [gender_distribution[name] for name in gender_names]
    gender_counts = _allocate_category_counts(count, gender_percentages)
    genders = [name for name, amount in zip(gender_names, gender_counts, strict=True) for _ in range(amount)]
    rng.shuffle(genders)
    return list(zip(ages, genders, strict=True))


def _requested_config(config: GenerationConfig) -> dict[str, Any]:
    result = config.model_dump(mode="json")
    if result["department_ids"] is not None:
        result["department_ids"] = sorted(result["department_ids"])
    return result


def _load_scope(db: Session, hospital_id: int, config: GenerationConfig) -> tuple[Hospital, list[Department], list[Bed]]:
    hospital = db.scalar(select(Hospital).where(Hospital.id == hospital_id))
    if hospital is None:
        raise HTTPException(status_code=404, detail="Hospital not found.")
    if hospital.is_archived:
        raise HTTPException(status_code=409, detail="Restore this hospital before generating a dataset.")

    query = select(Department).where(Department.hospital_id == hospital_id)
    if config.department_ids is None:
        query = query.where(Department.is_archived.is_(False)).order_by(Department.id)
    else:
        query = query.where(Department.id.in_(config.department_ids)).order_by(Department.id)
    departments = list(db.scalars(query).all())
    if config.department_ids is not None and len(departments) != len(config.department_ids):
        raise HTTPException(status_code=404, detail="One or more departments were not found in this hospital.")
    if any(department.is_archived for department in departments):
        raise HTTPException(status_code=409, detail="Archived departments cannot be included in generation.")
    selected_ids = {department.id for department in departments}
    if any(row.department_id not in selected_ids for row in config.department_demand_weights):
        raise HTTPException(status_code=422, detail="Department demand weights must reference active departments selected for this hospital.")
    if any(row.department_id not in selected_ids for row in config.department_length_of_stay_profiles):
        raise HTTPException(status_code=422, detail="Department length-of-stay profiles must reference active departments selected for this hospital.")
    if any(row.department_id not in selected_ids for row in config.department_bed_turnaround_profiles):
        raise HTTPException(status_code=422, detail="Department bed turnaround profiles must reference active departments selected for this hospital.")

    department_ids = [department.id for department in departments]
    beds = []
    if department_ids:
        beds = list(db.scalars(
            select(Bed)
            .where(
                Bed.hospital_id == hospital_id,
                Bed.department_id.in_(department_ids),
                Bed.status == "operational",
            )
            .order_by(Bed.id)
        ).all())
    if config.target_admissions and not beds:
        raise HTTPException(status_code=409, detail="Generation requires at least one operational bed in the selected departments.")
    return hospital, departments, beds


def _preview_digest(hospital: Hospital, departments: list[Department], beds: list[Bed], config: GenerationConfig) -> str:
    canonical = {
        "hospital_id": hospital.id,
        "workspace_id": hospital.workspace_id,
        "config": _requested_config(config),
        "departments": [{"id": row.id, "code": row.code, "name": row.name} for row in departments],
        "operational_beds": [{"id": row.id, "department_id": row.department_id} for row in beds],
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _turnaround_preview_counts(plan: list[dict[str, Any]], window_end_exclusive: datetime) -> tuple[int, int]:
    intervals: list[tuple[int, datetime]] = []
    for event in plan:
        if event["status"] != "assigned":
            continue
        transfer_bed = event.get("transfer_bed")
        transfer_at = event.get("transfer_at")
        discharged_at = event.get("discharged_at")
        if transfer_bed is not None and transfer_at is not None:
            seconds = event["turnaround_seconds"]
            if seconds > 0:
                intervals.append((event["bed"].id, transfer_at + timedelta(seconds=seconds)))
            if discharged_at is not None and event["transfer_turnaround_seconds"] > 0:
                intervals.append((transfer_bed.id, discharged_at + timedelta(seconds=event["transfer_turnaround_seconds"])))
        elif discharged_at is not None and event["turnaround_seconds"] > 0:
            intervals.append((event["bed"].id, discharged_at + timedelta(seconds=event["turnaround_seconds"])))
    return len(intervals), sum(completed_at > window_end_exclusive for _, completed_at in intervals)


def preview_generation(db: Session, hospital_id: int, config: GenerationConfig) -> GenerationPreviewRead:
    hospital, departments, beds = _load_scope(db, hospital_id, config)
    if config.target_admissions > 0 and not beds:
        raise HTTPException(status_code=409, detail="Generation requires at least one operational bed in the selected departments.")
    days = (config.end_date - config.start_date).days + 1
    total_beds = len(beds)
    peak = _scenario_peak(config, total_beds)
    projected_admissions = _scenario_admission_count(config)
    demographics = _generate_patient_demographics(projected_admissions, config.patient_profile, config.seed)
    admission_types = _generate_admission_types(config, projected_admissions)
    arrival_times = _generate_arrival_timestamps(config, admission_types)
    plan = _build_generation_plan(config, departments, beds, demographics, admission_types, arrival_times)
    turnaround_events, beds_cleaning_at_end = _turnaround_preview_counts(
        plan, datetime.combine(config.end_date + timedelta(days=1), time.min, tzinfo=timezone.utc).replace(tzinfo=None)
    )
    counts = {department.id: 0 for department in departments}
    for bed in beds:
        counts[bed.department_id] += 1
    return GenerationPreviewRead(
        hospital_id=hospital.id,
        hospital_name=hospital.name,
        workspace_id=hospital.workspace_id,
        start_date=config.start_date,
        end_date=config.end_date,
        target_admissions=config.target_admissions,
        projected_admissions=projected_admissions,
        target_occupancy_pct=config.target_occupancy_pct,
        scenario=config.scenario,
        patient_profile=config.patient_profile,
        arrival_profile=config.arrival_profile,
        length_of_stay_profile=config.length_of_stay_profile,
        department_length_of_stay_profiles=config.department_length_of_stay_profiles,
        projected_discharges=sum(event["discharged_at"] is not None for event in plan),
        projected_ongoing_admissions=sum(event["status"] == "assigned" and event["discharged_at"] is None for event in plan),
        projected_assigned_admissions=sum(event["status"] == "assigned" for event in plan),
        projected_waiting_patients=sum(event["status"] == "waiting" for event in plan),
        projected_max_wait_exceeded=sum(event["status"] == "max_wait_exceeded" for event in plan),
        projected_unresolved_requests=sum(event["status"] != "assigned" for event in plan),
        projected_average_wait_minutes=(sum(event["waiting_duration"].total_seconds() for event in plan if event["waiting_duration"] is not None) / max(1, sum(event["status"] == "assigned" for event in plan)) / 60),
        projected_maximum_wait_minutes=max((event["waiting_duration"].total_seconds() / 60 for event in plan if event["waiting_duration"] is not None), default=0),
        projected_turnaround_events=turnaround_events,
        projected_beds_cleaning_at_window_end=beds_cleaning_at_end,
        waiting_queue=config.waiting_queue,
        bed_turnaround_profile=config.bed_turnaround_profile,
        department_bed_turnaround_profiles=config.department_bed_turnaround_profiles,
        effective_admission_mix=_effective_admission_mix(config),
        seed=config.seed,
        departments=[
            {"department_id": department.id, "department_name": department.name, "operational_beds": counts[department.id]}
            for department in departments
        ],
        total_operational_beds=total_beds,
        planned_peak_occupied_beds=peak,
        occupancy_snapshots_planned=days * len(departments),
        preview_token=_preview_digest(hospital, departments, beds, config),
    )


def _check_generated_intervals(assignments: list[dict[str, Any]], beds_by_id: dict[int, Bed]) -> None:
    by_bed: dict[int, list[tuple[datetime, datetime, int]]] = {}
    by_admission: dict[int, list[tuple[datetime, datetime, int]]] = {}
    for row in assignments:
        if row["end_at"] is not None and row["end_at"] <= row["start_at"]:
            raise ValueError("Generated assignment has a non-positive interval.")
        bed = beds_by_id[row["bed_id"]]
        if bed.hospital_id != row["hospital_id"] or bed.department_id != row["department_id"] or bed.status != "operational":
            raise ValueError("Generated assignment references a bed outside its operational hospital department.")
        interval = (row["start_at"], row["end_at"] or datetime.max, row["admission_id"])
        by_bed.setdefault(row["bed_id"], []).append(interval)
        by_admission.setdefault(row["admission_id"], []).append(interval)
    for intervals in (*by_bed.values(), *by_admission.values()):
        intervals.sort(key=lambda item: item[0])
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1]:
                raise ValueError("Generated bed assignments overlap.")


def _sample_length_of_stay(
    profile: LengthOfStayProfile,
    rng: random.Random,
    scenario: str,
    age_years: int,
) -> timedelta:
    if profile.distribution == "fixed":
        days = profile.mode_days
    else:
        days = rng.triangular(profile.minimum_days, profile.maximum_days, profile.mode_days)
    if scenario == "seasonal_disease_surge":
        seasonal_factor = 1.25 if age_years >= 65 else 0.75
        days = min(profile.maximum_days, max(profile.minimum_days, days * seasonal_factor))
    return timedelta(seconds=max(1, round(days * 86_400)))


def _sample_turnaround_seconds(profile: BedTurnaroundProfile, rng: random.Random) -> int:
    if profile.distribution == "fixed":
        hours = profile.mode_hours
    else:
        hours = rng.triangular(profile.minimum_hours, profile.maximum_hours, profile.mode_hours)
    return max(0, round(hours * 3600))


def _build_generation_plan(
    config: GenerationConfig,
    departments: list[Department],
    beds: list[Bed],
    demographics: list[tuple[int, str]],
    admission_types: list[str],
    initial_arrivals: list[datetime],
) -> list[dict[str, Any]]:
    """Simulate request queueing, deterministic assignments, LOS and turnaround intervals."""
    count = len(admission_types)
    if not count:
        return []
    bed_rng = random.Random(config.seed)
    bed_order = _scenario_bed_order(beds, departments, config, bed_rng)
    slots = bed_order[:max(1, _scenario_peak(config, len(beds)))]
    if not slots:
        raise HTTPException(status_code=409, detail="Generation requires operational beds for the selected scope.")
    last_valid = datetime.combine(config.end_date + timedelta(days=1), time.min, tzinfo=timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    start_at = datetime.combine(config.start_date, time.min, tzinfo=timezone.utc).replace(tzinfo=None)
    stay_rng = random.Random(f"bedsynth-length-of-stay-v1:{config.seed}")
    turnaround_rng = random.Random(f"bedsynth-turnaround-v1:{config.seed}")
    profile_by_department = {row.department_id: row for row in config.department_length_of_stay_profiles}
    turnaround_profiles = {row.department_id: row for row in config.department_bed_turnaround_profiles}
    available_at = {bed.id: start_at for bed in slots}
    max_wait = timedelta(hours=config.waiting_queue.maximum_wait_hours)
    priority_rank = {"emergency": 0, "planned": 1} if config.waiting_queue.priority_policy == "emergency_first" else {"planned": 0, "emergency": 1}
    arrivals = sorted((initial_arrivals[index], index, admission_types[index]) for index in range(count))
    pending: list[tuple[datetime, int, str]] = []
    selected_by_patient: dict[int, dict[str, Any]] = {}
    arrival_index = 0
    now = arrivals[0][0]
    while arrival_index < count or pending:
        while arrival_index < count and arrivals[arrival_index][0] <= now:
            pending.append(arrivals[arrival_index])
            arrival_index += 1
        pending = [item for item in pending if item[0] + max_wait >= now]
        while pending:
            available_beds = [bed for bed in slots if available_at[bed.id] <= now]
            if not available_beds:
                break
            pending.sort(key=lambda item: (
                priority_rank[item[2]] if config.waiting_queue.priority_policy != "arrival_order" else 0,
                item[0], item[1],
            ))
            requested_at, patient_index, admission_type = pending.pop(0)
            preferred_slots = slots[patient_index % len(slots):] + slots[:patient_index % len(slots)]
            bed = next(candidate for candidate in preferred_slots if candidate in available_beds)
            assigned_at = now
            waited = assigned_at - requested_at
            age_years = demographics[patient_index][0]
            profile = profile_by_department.get(bed.department_id, config.length_of_stay_profile)
            stay = _sample_length_of_stay(profile, stay_rng, config.scenario, age_years)
            intended_end = assigned_at + stay
            discharged_at = intended_end if intended_end <= last_valid else None
            turnaround = timedelta(0)
            if discharged_at is not None:
                turn_profile = turnaround_profiles.get(bed.department_id, config.bed_turnaround_profile)
                turnaround = timedelta(seconds=_sample_turnaround_seconds(turn_profile, turnaround_rng))
            available_at[bed.id] = discharged_at + turnaround if discharged_at is not None else datetime.max
            selected_by_patient[patient_index] = {
                "patient_index": patient_index, "admission_type": admission_type, "bed": bed,
                "department_id": bed.department_id, "admitted_at": requested_at, "requested_at": requested_at,
                "scheduled_at": requested_at if admission_type == "planned" else None,
                "bed_assigned_at": assigned_at, "waiting_duration": waited, "status": "assigned",
                "outcome_reason": None, "intended_end": intended_end, "discharged_at": discharged_at,
                "turnaround_seconds": int(turnaround.total_seconds()),
            }
        if arrival_index >= count and not pending:
            break
        candidates = []
        if arrival_index < count:
            candidates.append(arrivals[arrival_index][0])
        candidates.extend(value for value in available_at.values() if now < value <= last_valid)
        candidates.extend(item[0] + max_wait + timedelta(microseconds=1) for item in pending if item[0] + max_wait < last_valid)
        if not candidates:
            break
        next_event = min(candidates)
        if next_event <= now:
            next_event = now + timedelta(microseconds=1)
        now = next_event
    selected: list[dict[str, Any]] = list(selected_by_patient.values())
    for requested_at, patient_index, admission_type in arrivals:
        if patient_index in selected_by_patient:
            continue
        status = "max_wait_exceeded" if requested_at + max_wait <= last_valid else "waiting"
        # Keep the requested department intent consistent with deterministic bed order.
        intended_bed = slots[patient_index % len(slots)]
        selected.append({"patient_index": patient_index, "admission_type": admission_type, "bed": None,
                         "department_id": intended_bed.department_id, "requested_at": requested_at,
                         "scheduled_at": requested_at if admission_type == "planned" else None,
                         "bed_assigned_at": None, "waiting_duration": None, "status": status,
                         "outcome_reason": "max_wait_exceeded" if status == "max_wait_exceeded" else "waiting_at_window_end",
                         "admitted_at": requested_at, "intended_end": None, "discharged_at": None})
    selected.sort(key=lambda event: event["patient_index"])
    # Reproduce the established seeded transfer draw order and reserve each
    # vacated destination through its own cleaning interval.
    transfer_rng = random.Random(config.seed)
    transfer_bed_order = _scenario_bed_order(beds, departments, config, transfer_rng)
    for _ in range(count):
        transfer_rng.choice(AGE_BANDS)
    transfer_intervals: dict[int, list[tuple[datetime, datetime | None]]] = {}
    transfer_turnaround_rng = random.Random(f"bedsynth-transfer-turnaround-v1:{config.seed}")
    for event in selected:
        if event["status"] != "assigned":
            continue
        initial_bed = event["bed"]
        assigned_at = event["bed_assigned_at"]
        discharged_at = event["discharged_at"]
        observed_end = discharged_at or last_valid
        spare_beds = [bed for bed in transfer_bed_order if bed.id not in {slot.id for slot in slots}]
        if config.scenario == "emergency_surge":
            spare_beds = [bed for bed in spare_beds if bed.department_id != initial_bed.department_id]
        transfer_at = assigned_at + (observed_end - assigned_at) / 2
        spare_beds = [bed for bed in spare_beds if all(
            interval_end is not None and transfer_at >= interval_end
            or discharged_at is not None and discharged_at <= interval_start
            for interval_start, interval_end in transfer_intervals.get(bed.id, [])
        )]
        denominator = 2 if config.scenario == "emergency_surge" else 5
        transfer_bed = None
        if spare_beds and observed_end - assigned_at >= timedelta(hours=4) and transfer_rng.randrange(denominator) == 0:
            source_profile = turnaround_profiles.get(initial_bed.department_id, config.bed_turnaround_profile)
            source_seconds = _sample_turnaround_seconds(source_profile, transfer_turnaround_rng)
            cleaning_complete = transfer_at + timedelta(seconds=source_seconds)
            source_conflict = any(
                other is not event and other["status"] == "assigned" and other["bed"].id == initial_bed.id
                and transfer_at <= other["bed_assigned_at"] < cleaning_complete
                for other in selected
            )
            if not source_conflict:
                transfer_bed = spare_beds[0]
                destination_profile = turnaround_profiles.get(transfer_bed.department_id, config.bed_turnaround_profile)
                destination_seconds = _sample_turnaround_seconds(destination_profile, transfer_turnaround_rng)
                transfer_intervals.setdefault(transfer_bed.id, []).append((transfer_at, discharged_at + timedelta(seconds=destination_seconds) if discharged_at is not None else None))
                event["transfer_bed"] = transfer_bed
                event["transfer_at"] = transfer_at
                event["transfer_turnaround_seconds"] = destination_seconds
                available_at[initial_bed.id] = cleaning_complete
                event["turnaround_seconds"] = source_seconds
        if event.get("transfer_bed") is None:
            event["transfer_bed"] = None
            event["transfer_at"] = None
            event["transfer_turnaround_seconds"] = 0
    return selected


def _write_generation_data(db: Session, run: GenerationRun, config: GenerationConfig, departments: list[Department], beds: list[Bed]) -> None:
    rng = random.Random(config.seed)
    start_at = datetime.combine(config.start_date, time.min, tzinfo=timezone.utc).replace(tzinfo=None)
    end_exclusive = datetime.combine(config.end_date + timedelta(days=1), time.min, tzinfo=timezone.utc).replace(tzinfo=None)
    last_valid_time = end_exclusive - timedelta(seconds=1)
    beds_by_id = {bed.id: bed for bed in beds}

    total_beds = len(beds)
    peak = _scenario_peak(config, total_beds)
    admission_count = _scenario_admission_count(config)
    bed_order = _scenario_bed_order(beds, departments, config, rng)
    # Preserve the operational RNG sequence used by generator v2: it consumed
    # one seeded draw per patient's legacy age band before assigning transfers.
    # Demographics use a separate versioned stream so profile changes don't
    # alter admissions, transfers, or occupancy for the same operational seed.
    for _ in range(admission_count):
        rng.choice(AGE_BANDS)
    demographics = _generate_patient_demographics(admission_count, config.patient_profile, config.seed)
    admission_types = _generate_admission_types(config, admission_count)
    arrival_times = _generate_arrival_timestamps(config, admission_types)

    patients: list[SyntheticPatient] = []
    for index, (age_years, gender) in enumerate(demographics, start=1):
        patients.append(SyntheticPatient(
            run_id=run.run_id,
            workspace_id=run.workspace_id,
            hospital_id=run.hospital_id,
            synthetic_patient_id=f"SYN-{config.seed:010d}-{index:06d}",
            age_band=_legacy_age_band(age_years),
            age_years=age_years,
            gender=gender,
            created_at=run.started_at,
        ))
    db.add_all(patients)
    db.flush()

    admissions: list[Admission] = []
    episode_rows: list[dict[str, Any]] = []
    queue_rows: list[WaitingQueueEntry] = []
    slot_beds = bed_order[:max(1, peak)] if admission_count else []
    plan = _build_generation_plan(config, departments, beds, demographics, admission_types, arrival_times)
    for event in plan:
        patient_index = event["patient_index"]
        patient = patients[patient_index]
        if event["status"] != "assigned":
            continue
        admitted_at = event["admitted_at"]
        admission_type = event["admission_type"]
        selected_bed: Bed = event["bed"]
        discharged_at = event["discharged_at"]
        admission = Admission(
            run_id=run.run_id,
            workspace_id=run.workspace_id,
            hospital_id=run.hospital_id,
            patient_id=patient.id,
            department_id=selected_bed.department_id,
            initial_bed_id=selected_bed.id,
            admitted_at=admitted_at,
            admission_type=admission_type,
            requested_at=event["requested_at"],
            scheduled_at=event["scheduled_at"],
            bed_assigned_at=event["bed_assigned_at"],
            status="discharged" if discharged_at is not None else "admitted",
        )
        admissions.append(admission)
        episode_rows.append({
            "admission": admission, "bed": selected_bed, "start": event["bed_assigned_at"],
            "end": discharged_at, "intended_end": event["intended_end"], "plan": event,
        })
    db.add_all(admissions)
    db.flush()
    admission_by_patient = {row.patient_id: row for row in admissions}
    for event in plan:
        patient = patients[event["patient_index"]]
        queue_rows.append(WaitingQueueEntry(
            run_id=run.run_id, workspace_id=run.workspace_id, hospital_id=run.hospital_id,
            request_number=event["patient_index"] + 1, patient_id=patient.id,
            department_id=event["department_id"],
            admission_id=admission_by_patient[patient.id].id if event["status"] == "assigned" else None,
            requested_at=event["requested_at"], priority=event["admission_type"], status=event["status"],
            bed_assigned_at=event["bed_assigned_at"],
            waiting_duration_seconds=round(event["waiting_duration"].total_seconds()) if event["waiting_duration"] is not None else None,
            outcome_reason=event["outcome_reason"],
        ))
    db.add_all(queue_rows)

    assignments: list[dict[str, Any]] = []
    discharges: list[Discharge] = []
    transfers: list[BedTransfer] = []
    transfer_intervals_by_bed: dict[int, list[tuple[datetime, datetime | None]]] = {}
    for index, episode in enumerate(episode_rows):
        admission = episode["admission"]
        initial_bed: Bed = episode["bed"]
        admitted_at: datetime = episode["start"]
        discharged_at: datetime | None = episode["end"]
        planned_transfer_bed = episode["plan"].get("transfer_bed")
        transfer_at = episode["plan"].get("transfer_at")
        transfer_bed = planned_transfer_bed

        if transfer_bed is None:
            assignments.append({
                "run_id": run.run_id, "workspace_id": run.workspace_id, "hospital_id": run.hospital_id,
                "admission_id": admission.id, "department_id": initial_bed.department_id, "bed_id": initial_bed.id,
                "start_at": admitted_at, "end_at": discharged_at,
                "turnaround_seconds": episode["plan"]["turnaround_seconds"],
            })
        else:
            assignments.extend((
                {
                    "run_id": run.run_id, "workspace_id": run.workspace_id, "hospital_id": run.hospital_id,
                    "admission_id": admission.id, "department_id": initial_bed.department_id, "bed_id": initial_bed.id,
                    "start_at": admitted_at, "end_at": transfer_at,
                    "turnaround_seconds": episode["plan"]["turnaround_seconds"],
                },
                {
                    "run_id": run.run_id, "workspace_id": run.workspace_id, "hospital_id": run.hospital_id,
                    "admission_id": admission.id, "department_id": transfer_bed.department_id, "bed_id": transfer_bed.id,
                    "start_at": transfer_at, "end_at": discharged_at,
                    "turnaround_seconds": episode["plan"]["transfer_turnaround_seconds"],
                },
            ))
            transfers.append(BedTransfer(
                run_id=run.run_id,
                workspace_id=run.workspace_id,
                hospital_id=run.hospital_id,
                admission_id=admission.id,
                sequence_number=1,
                source_department_id=initial_bed.department_id,
                destination_department_id=transfer_bed.department_id,
                source_bed_id=initial_bed.id,
                destination_bed_id=transfer_bed.id,
                transferred_at=transfer_at,
            ))
        if discharged_at is not None:
            discharges.append(Discharge(
                run_id=run.run_id,
                workspace_id=run.workspace_id,
                hospital_id=run.hospital_id,
                admission_id=admission.id,
                discharged_at=discharged_at,
            ))

    _check_generated_intervals(assignments, beds_by_id)
    turnaround_seconds_by_assignment = {
        (row["admission_id"], row["bed_id"], row["start_at"], row["end_at"]): row.get("turnaround_seconds", 0)
        for row in assignments
    }
    assignment_objects = [BedAssignment(**{key: value for key, value in row.items() if key != "turnaround_seconds"}) for row in assignments]
    db.add_all(assignment_objects)
    db.add_all(discharges)
    db.add_all(transfers)
    db.flush()

    turnarounds: list[BedTurnaround] = []
    for assignment in sorted(assignment_objects, key=lambda row: (row.start_at, row.admission_id, row.bed_id)):
        if assignment.end_at is None:
            continue
        seconds = turnaround_seconds_by_assignment.get((assignment.admission_id, assignment.bed_id, assignment.start_at, assignment.end_at), 0)
        if seconds <= 0:
            continue
        turnarounds.append(BedTurnaround(
            run_id=run.run_id, workspace_id=run.workspace_id, hospital_id=run.hospital_id,
            assignment_id=assignment.id, admission_id=assignment.admission_id, bed_id=assignment.bed_id,
            department_id=assignment.department_id, started_at=assignment.end_at,
            completed_at=assignment.end_at + timedelta(seconds=seconds), duration_seconds=seconds,
        ))
    db.add_all(turnarounds)
    db.flush()

    assignments_by_department: dict[int, list[dict[str, Any]]] = {department.id: [] for department in departments}
    for assignment in assignments:
        assignments_by_department[assignment["department_id"]].append(assignment)
    beds_per_department = {department.id: sum(bed.department_id == department.id for bed in beds) for department in departments}
    snapshots: list[OccupancySnapshot] = []
    snapshot_day = config.start_date
    while snapshot_day <= config.end_date:
        snapshot_at = datetime.combine(snapshot_day, time(hour=12), tzinfo=timezone.utc).replace(tzinfo=None)
        for department in departments:
            operational = beds_per_department[department.id]
            occupied = sum(
                assignment["start_at"] <= snapshot_at and (assignment["end_at"] is None or snapshot_at < assignment["end_at"])
                for assignment in assignments_by_department[department.id]
            )
            snapshots.append(OccupancySnapshot(
                run_id=run.run_id,
                workspace_id=run.workspace_id,
                hospital_id=run.hospital_id,
                department_id=department.id,
                snapshot_at=snapshot_at,
                operational_beds=operational,
                occupied_beds=occupied,
                available_beds=operational - occupied,
                occupancy_pct=(occupied / operational * 100) if operational else None,
            ))
        snapshot_day += timedelta(days=1)
    db.add_all(snapshots)
    db.flush()

    run.patients_count = len(patients)
    run.admissions_count = len(admissions)
    run.discharges_count = len(discharges)
    run.transfers_count = len(transfers)
    run.snapshots_count = len(snapshots)
    run.waiting_queue_count = len(queue_rows)
    run.bed_turnaround_count = len(turnarounds)


def generate_dataset(db: Session, hospital_id: int, payload: GenerationCreate, *, owner_user_id: int | None = None) -> GenerationRun:
    key = str(payload.idempotency_key)
    config = GenerationConfig.model_validate(payload.model_dump(exclude={"idempotency_key", "preview_token"}))
    requested = _requested_config(config)
    try:
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        hospital, departments, beds = _load_scope(db, hospital_id, config)
        existing = db.scalar(select(GenerationRun).where(
            GenerationRun.workspace_id == hospital.workspace_id,
            GenerationRun.idempotency_key == key,
        ))
        if existing is not None:
            if existing.hospital_id != hospital.id or existing.config.get("request") != requested or (owner_user_id is not None and existing.owner_user_id != owner_user_id):
                db.rollback()
                raise HTTPException(status_code=409, detail="This idempotency key was already used with a different configuration.")
            db.rollback()
            return existing
        if _preview_digest(hospital, departments, beds, config) != payload.preview_token:
            db.rollback()
            raise HTTPException(status_code=409, detail="Hospital configuration changed after preview. Review a fresh preview.")

        effective_config = {
            "request": requested,
            "scenario_name": SCENARIO_PRESETS[config.scenario]["name"],
            "scenario_policy": SCENARIO_PRESETS[config.scenario],
            "resolved_department_ids": [department.id for department in departments],
            "generator_version": GENERATOR_VERSION,
            "age_band_policy": list(AGE_BANDS),
            "transfer_policy": {
                **TRANSFER_POLICY,
                "seeded_selection": SCENARIO_PRESETS[config.scenario]["transfer_selection"],
            },
            "occupancy_snapshot_cadence": "daily at 12:00 UTC",
            "assignment_interval_policy": "half-open [start_at, end_at)",
            "occupancy_formula": "occupied_operational_beds / operational_beds * 100",
            "zero_operational_bed_denominator": None,
            "time_zone": "UTC",
            "admission_arrival_policy": {
                "arrival_sampling": "seeded-individual-weighted-hour-within-UTC-window-v1",
                "planned_admission_odds_multiplier": 1.0,
                "emergency_surge_odds_multiplier": SCENARIO_PRESETS[config.scenario].get("emergency_odds_multiplier", 1.0),
                "planned_request_time": "scheduled arrival instant for new runs",
                "emergency_request_time": "arrival instant",
                "bed_assignment": "deterministic queue allocation; assigned_at >= requested_at",
                "department_weights": "configured department weight overrides scenario name-based bias for that department; default weight is 1",
            },
            "length_of_stay_policy": {
                "unit": "days",
                "distribution": "fixed or seeded triangular (minimum, mode, maximum)",
                "department_profiles": "selected-department override; global profile is the fallback",
                "scenario_adjustment": "Seasonal Disease Surge applies the existing age-band multiplier and clamps the result to the configured profile bounds",
                "observation_window": "admissions not discharged by the final configured UTC instant remain admitted with an open bed assignment; no discharge is inferred",
            },
            "waiting_queue_policy": {
                "priority_policy": config.waiting_queue.priority_policy,
                "maximum_wait_hours": config.waiting_queue.maximum_wait_hours,
                "waiting_definition": "bed_assigned_at - requested_at, in seconds",
                "window_end_outcome": "unassigned requests with a remaining wait allowance are recorded as waiting; requests whose maximum wait expires within the window are max_wait_exceeded",
            },
            "bed_turnaround_policy": {
                "global_profile": config.bed_turnaround_profile.model_dump(),
                "department_profiles": [item.model_dump() for item in config.department_bed_turnaround_profiles],
                "duration_unit": "hours in configuration, seconds in bed_turnaround.csv",
                "interval": "half-open [started_at, completed_at); starts at assignment end; does not extend patient LOS",
                "ongoing_assignment": "no turnaround event is recorded for an assignment without end_at",
            },
        }
        run = GenerationRun(
            run_id=str(uuid4()),
            workspace_id=hospital.workspace_id,
            hospital_id=hospital.id,
            owner_user_id=owner_user_id,
            idempotency_key=key,
            config=effective_config,
            seed=config.seed,
            status="generating",
        )
        db.add(run)
        db.commit()
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(GenerationRun).where(GenerationRun.workspace_id == hospital.workspace_id, GenerationRun.idempotency_key == key))
        if existing is not None and existing.hospital_id == hospital_id and existing.config.get("request") == requested:
            return existing
        raise HTTPException(status_code=409, detail="A generation with this idempotency key already exists.") from exc

    try:
        # Re-read the stable scope within the data transaction. The initial run record
        # remains as history if any generated row fails validation or persistence.
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        run = db.get(GenerationRun, run.run_id)
        hospital, departments, beds = _load_scope(db, hospital_id, config)
        if _preview_digest(hospital, departments, beds, config) != payload.preview_token:
            raise ValueError("Hospital configuration changed after preview; the request must be previewed again.")
        department_names = {department.id: department.name for department in departments}
        department_ids = list(department_names)
        inventory_beds = list(db.scalars(
            select(Bed)
            .where(Bed.hospital_id == hospital.id, Bed.department_id.in_(department_ids))
            .order_by(Bed.department_id, Bed.id)
        ).all()) if department_ids else []
        generation_pool_ids = {bed.id for bed in beds}
        run_config = dict(run.config or {})
        run_config["resolved_bed_inventory"] = [
            {
                "hospital_id": bed.hospital_id,
                "bed_id": bed.id,
                "bed_code": bed.code,
                "department_id": bed.department_id,
                "department_name": department_names[bed.department_id],
                "bed_category": bed.category,
                "bed_status": bed.status,
                "generation_pool_member": bed.id in generation_pool_ids,
            }
            for bed in inventory_beds
        ]
        run.config = run_config
        _write_generation_data(db, run, config, departments, beds)
        run.status = "completed"
        run.completed_at = utc_now()
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_run = db.get(GenerationRun, run.run_id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.completed_at = utc_now()
            failed_run.error_message = f"Generation failed: {type(exc).__name__}: {str(exc)[:900]}"
            db.commit()
        return failed_run
    return run
