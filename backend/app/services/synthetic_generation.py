"""Deterministic synthetic hospital operations generation service."""

from __future__ import annotations

import hashlib
import json
import math
import random
from bisect import bisect_right
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
    Department,
    Discharge,
    GenerationRun,
    Hospital,
    OccupancySnapshot,
    SyntheticPatient,
    utc_now,
)
from app.schemas import GenerationConfig, GenerationCreate, GenerationPreviewRead, PatientProfileConfig

GENERATOR_VERSION = "deterministic-3"
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
        "arrival_profile": "front-loaded high-volume cohort followed by lower-volume cohorts",
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


def _scenario_bed_order(beds: list[Bed], departments: list[Department], config: GenerationConfig, rng: random.Random) -> list[Bed]:
    preset = SCENARIO_PRESETS[config.scenario]
    if not preset["department_bias"]:
        result = beds.copy()
        rng.shuffle(result)
        return result
    names = {department.id: department.name.casefold() for department in departments}
    biases = preset["department_bias"]
    # Order departments by their explicit scenario priority, randomizing beds
    # within each group while keeping every operational bed unique.
    grouped: dict[float, list[Bed]] = {}
    for bed in beds:
        weight = max(
            [factor for keyword, factor in biases.items() if keyword in names.get(bed.department_id, "")]
            or [1.0]
        )
        grouped.setdefault(weight, []).append(bed)
    result = []
    for weight in sorted(grouped, reverse=True):
        rng.shuffle(grouped[weight])
        result.extend(grouped[weight])
    return result


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


def preview_generation(db: Session, hospital_id: int, config: GenerationConfig) -> GenerationPreviewRead:
    hospital, departments, beds = _load_scope(db, hospital_id, config)
    if config.target_admissions > 0 and not beds:
        raise HTTPException(status_code=409, detail="Generation requires at least one operational bed in the selected departments.")
    days = (config.end_date - config.start_date).days + 1
    total_beds = len(beds)
    peak = _scenario_peak(config, total_beds)
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
        projected_admissions=_scenario_admission_count(config),
        target_occupancy_pct=config.target_occupancy_pct,
        scenario=config.scenario,
        patient_profile=config.patient_profile,
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
        if row["end_at"] <= row["start_at"]:
            raise ValueError("Generated assignment has a non-positive interval.")
        bed = beds_by_id[row["bed_id"]]
        if bed.hospital_id != row["hospital_id"] or bed.department_id != row["department_id"] or bed.status != "operational":
            raise ValueError("Generated assignment references a bed outside its operational hospital department.")
        interval = (row["start_at"], row["end_at"], row["admission_id"])
        by_bed.setdefault(row["bed_id"], []).append(interval)
        by_admission.setdefault(row["admission_id"], []).append(interval)
    for intervals in (*by_bed.values(), *by_admission.values()):
        intervals.sort(key=lambda item: item[0])
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1]:
                raise ValueError("Generated bed assignments overlap.")


def _write_generation_data(db: Session, run: GenerationRun, config: GenerationConfig, departments: list[Department], beds: list[Bed]) -> None:
    rng = random.Random(config.seed)
    start_at = datetime.combine(config.start_date, time.min, tzinfo=timezone.utc).replace(tzinfo=None)
    end_exclusive = datetime.combine(config.end_date + timedelta(days=1), time.min, tzinfo=timezone.utc).replace(tzinfo=None)
    last_valid_time = end_exclusive - timedelta(seconds=1)
    horizon = last_valid_time - start_at
    beds_by_id = {bed.id: bed for bed in beds}

    total_beds = len(beds)
    peak = _scenario_peak(config, total_beds)
    admission_count = _scenario_admission_count(config)
    if config.scenario == "emergency_surge" and admission_count:
        baseline_peak = max(1, min(total_beds, config.target_admissions, math.ceil(total_beds * config.target_occupancy_pct / 100)))
        cohort_count = max(1, math.ceil(admission_count / baseline_peak))
        first_cohort_size = min(peak, admission_count)
        remaining = admission_count - first_cohort_size
        later_count = cohort_count - 1
        if later_count:
            base_size, extra = divmod(remaining, later_count)
            cohort_sizes = [first_cohort_size, *(base_size + (1 if index < extra else 0) for index in range(later_count))]
            cohort_sizes = [size for size in cohort_sizes if size > 0]
        else:
            cohort_sizes = [first_cohort_size]
    else:
        cohort_size = max(1, peak) if admission_count else 0
        cohort_count = math.ceil(admission_count / cohort_size) if cohort_size else 0
        cohort_sizes = [cohort_size] * cohort_count
        if cohort_sizes and sum(cohort_sizes) > admission_count:
            cohort_sizes[-1] -= sum(cohort_sizes) - admission_count
    cohort_offsets = []
    next_offset = 0
    for size in cohort_sizes:
        cohort_offsets.append(next_offset)
        next_offset += size
    cohort_count = len(cohort_sizes)
    cohort_duration = horizon / cohort_count if cohort_count else timedelta(0)
    bed_order = _scenario_bed_order(beds, departments, config, rng)
    # Preserve the operational RNG sequence used by generator v2: it consumed
    # one seeded draw per patient's legacy age band before assigning transfers.
    # Demographics use a separate versioned stream so profile changes don't
    # alter admissions, transfers, or occupancy for the same operational seed.
    for _ in range(admission_count):
        rng.choice(AGE_BANDS)
    demographics = _generate_patient_demographics(admission_count, config.patient_profile, config.seed)

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
    for index, patient in enumerate(patients):
        cohort_index = bisect_right(cohort_offsets, index) - 1
        position = index - cohort_offsets[cohort_index]
        admitted_at = start_at + cohort_duration * cohort_index
        discharged_at = start_at + cohort_duration * (cohort_index + 1)
        if config.scenario == "seasonal_disease_surge" and (patient.age_years or 0) < 65:
            # The proposed seasonal preset selects older fictional age bands for
            # relatively longer stays; no diagnosis or clinical meaning is generated.
            discharged_at = admitted_at + cohort_duration * 0.75
        if cohort_index == cohort_count - 1:
            discharged_at = last_valid_time
        if discharged_at <= admitted_at:
            discharged_at = min(last_valid_time, admitted_at + timedelta(seconds=1))
        selected_bed = bed_order[(cohort_offsets[cohort_index] + position) % total_beds]
        admission = Admission(
            run_id=run.run_id,
            workspace_id=run.workspace_id,
            hospital_id=run.hospital_id,
            patient_id=patient.id,
            department_id=selected_bed.department_id,
            initial_bed_id=selected_bed.id,
            admitted_at=admitted_at,
            status="discharged",
        )
        admissions.append(admission)
        episode_rows.append({"admission": admission, "bed": selected_bed, "start": admitted_at, "end": discharged_at})
    db.add_all(admissions)
    db.flush()

    assignments: list[dict[str, Any]] = []
    discharges: list[Discharge] = []
    transfers: list[BedTransfer] = []
    transfer_destinations_by_cohort: dict[int, set[int]] = {}
    for index, episode in enumerate(episode_rows):
        admission = episode["admission"]
        initial_bed: Bed = episode["bed"]
        admitted_at: datetime = episode["start"]
        discharged_at: datetime = episode["end"]
        cohort_index = bisect_right(cohort_offsets, index) - 1
        active_cohort_start = cohort_offsets[cohort_index]
        active_cohort_end = active_cohort_start + cohort_sizes[cohort_index]
        occupied_bed_ids = {episode_rows[position]["bed"].id for position in range(active_cohort_start, active_cohort_end)}
        reserved_destination_ids = transfer_destinations_by_cohort.setdefault(cohort_index, set())
        spare_beds = [bed for bed in bed_order if bed.id not in occupied_bed_ids and bed.id not in reserved_destination_ids]
        if config.scenario == "emergency_surge":
            cross_department = [bed for bed in spare_beds if bed.department_id != initial_bed.department_id]
            spare_beds = cross_department
        transfer_bed = None
        transfer_denominator = 2 if config.scenario == "emergency_surge" else 5
        if spare_beds and discharged_at - admitted_at >= timedelta(hours=4) and rng.randrange(transfer_denominator) == 0:
            transfer_bed = spare_beds.pop(0)
            reserved_destination_ids.add(transfer_bed.id)

        if transfer_bed is None:
            assignments.append({
                "run_id": run.run_id, "workspace_id": run.workspace_id, "hospital_id": run.hospital_id,
                "admission_id": admission.id, "department_id": initial_bed.department_id, "bed_id": initial_bed.id,
                "start_at": admitted_at, "end_at": discharged_at,
            })
        else:
            transfer_at = admitted_at + (discharged_at - admitted_at) / 2
            assignments.extend((
                {
                    "run_id": run.run_id, "workspace_id": run.workspace_id, "hospital_id": run.hospital_id,
                    "admission_id": admission.id, "department_id": initial_bed.department_id, "bed_id": initial_bed.id,
                    "start_at": admitted_at, "end_at": transfer_at,
                },
                {
                    "run_id": run.run_id, "workspace_id": run.workspace_id, "hospital_id": run.hospital_id,
                    "admission_id": admission.id, "department_id": transfer_bed.department_id, "bed_id": transfer_bed.id,
                    "start_at": transfer_at, "end_at": discharged_at,
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
        discharges.append(Discharge(
            run_id=run.run_id,
            workspace_id=run.workspace_id,
            hospital_id=run.hospital_id,
            admission_id=admission.id,
            discharged_at=discharged_at,
        ))

    _check_generated_intervals(assignments, beds_by_id)
    db.add_all([BedAssignment(**row) for row in assignments])
    db.add_all(discharges)
    db.add_all(transfers)
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
                assignment["start_at"] <= snapshot_at < assignment["end_at"]
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


def generate_dataset(db: Session, hospital_id: int, payload: GenerationCreate) -> GenerationRun:
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
            if existing.hospital_id != hospital.id or existing.config.get("request") != requested:
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
        }
        run = GenerationRun(
            run_id=str(uuid4()),
            workspace_id=hospital.workspace_id,
            hospital_id=hospital.id,
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
