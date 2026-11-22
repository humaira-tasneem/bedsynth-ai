"""Explicit, idempotent seed command for fictional demo hospitals.

Run from ``backend`` with ``python -m app.demo_seed``. This command is never
invoked during normal API startup.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.environment import load_backend_environment

# Use the same backend-relative .env loading as the API and account CLI. This
# runs before importing the database module, which reads DATABASE_URL.
load_backend_environment()

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.models import Bed, Department, Hospital, Workspace  # noqa: E402


DEMO_WORKSPACE_NAME = "BedSynth Demo Workspace"
DEMO_HOSPITAL_NAME = "Sunrise General Hospital"
DEMO_HOSPITAL_CODE = "SGH-001"

SUNRISE_DEPARTMENTS = (
    ("Cardiology", "CAR-01", 25),
    ("Emergency", "EMG-01", 20),
    ("General Medicine", "MED-01", 30),
    ("Neurology", "NEU-01", 20),
    ("Orthopedics", "ORT-01", 25),
)


@dataclass(frozen=True)
class DemoHospital:
    name: str
    code: str
    departments: tuple[tuple[str, str, int], ...]


DEMO_HOSPITALS = (
    DemoHospital(DEMO_HOSPITAL_NAME, DEMO_HOSPITAL_CODE, SUNRISE_DEPARTMENTS),
    DemoHospital("CityCare Multispecialty Hospital", "CCH-001", (
        ("Emergency", "EMG-01", 35),
        ("Cardiology", "CAR-01", 30),
        ("General Medicine", "MED-01", 40),
        ("Neurology", "NEU-01", 20),
        ("Orthopedics", "ORT-01", 25),
        ("Pediatrics", "PED-01", 25),
        ("Obstetrics & Gynecology", "OBG-01", 25),
    )),
    DemoHospital("Green Valley Community Hospital", "GVCH-001", (
        ("Emergency", "EMG-01", 10),
        ("General Medicine", "MED-01", 25),
        ("Pediatrics", "PED-01", 15),
        ("Maternity", "MAT-01", 10),
    )),
    DemoHospital("Apex Specialty Hospital", "ASH-001", (
        ("Cardiology", "CAR-01", 35),
        ("Cardiothoracic Surgery", "CTS-01", 20),
        ("Neurology", "NEU-01", 15),
        ("Orthopedics", "ORT-01", 15),
        ("Oncology", "ONC-01", 15),
    )),
)
# Preserve the original public constant used by callers and existing tests.
DEMO_DEPARTMENTS = SUNRISE_DEPARTMENTS


class DemoSeedConflict(ValueError):
    """Existing configuration conflicts with the safe seed assumptions."""


def _find_hospital(db: Session, spec: DemoHospital) -> Hospital | None:
    hospitals = list(
        db.scalars(select(Hospital).where(func.lower(Hospital.code) == spec.code.lower()))
    )
    if len(hospitals) > 1:
        raise DemoSeedConflict(
            f"Hospital code {spec.code} is duplicated across workspaces; review the records before seeding."
        )
    hospital = hospitals[0] if hospitals else None
    if hospital is not None:
        # The stable code identifies the seeded hospital. Its display name may
        # have been changed by an administrator and must not be overwritten.
        return hospital

    named_hospital = db.scalar(
        select(Hospital).where(func.lower(Hospital.name) == spec.name.lower())
    )
    if named_hospital is not None:
        raise DemoSeedConflict(
            f"{spec.name} already exists with a different hospital code; no changes were made."
        )
    return None


def _get_or_create_workspace(db: Session) -> Workspace:
    workspace = db.scalar(
        select(Workspace)
        .where(func.lower(Workspace.name) == DEMO_WORKSPACE_NAME.lower())
        .order_by(Workspace.id)
    )
    if workspace is None:
        workspace = Workspace(name=DEMO_WORKSPACE_NAME)
        db.add(workspace)
        db.flush()
    return workspace


def _get_or_create_department(
    db: Session, hospital: Hospital, name: str, code: str, capacity: int
) -> Department:
    department = db.scalar(
        select(Department).where(
            Department.hospital_id == hospital.id,
            func.lower(Department.code) == code.lower(),
        )
    )
    if department is not None:
        # Stable department codes let the seed fill missing inventory while
        # preserving administrator-edited names and capacities.
        return department

    named_department = db.scalar(
        select(Department).where(
            Department.hospital_id == hospital.id,
            func.lower(Department.name) == name.lower(),
        )
    )
    if named_department is not None:
        raise DemoSeedConflict(
            f"Department {name} already exists with a different code; no changes were made."
        )

    department = Department(
        hospital_id=hospital.id,
        name=name,
        code=code,
        bed_capacity=capacity,
    )
    db.add(department)
    db.flush()
    return department


def _add_missing_beds(db: Session, hospital: Hospital, department: Department) -> int:
    if department.is_archived:
        raise DemoSeedConflict(
            f"Department {department.code} is archived; restore it before seeding its inventory."
        )
    if department.bed_capacity is None:
        raise DemoSeedConflict(
            f"Department {department.code} has no configured bed capacity; set one before seeding."
        )

    non_retired_count = int(
        db.scalar(
            select(func.count(Bed.id)).where(
                Bed.department_id == department.id,
                Bed.status != "retired",
            )
        )
        or 0
    )
    if non_retired_count > department.bed_capacity:
        raise DemoSeedConflict(
            f"Department {department.code} has {non_retired_count} non-retired beds, above its configured capacity of {department.bed_capacity}; no changes were made."
        )

    missing = department.bed_capacity - non_retired_count
    if not missing:
        return 0

    # Use the stable department-code prefix and continue after the greatest
    # existing suffix. A hospital-wide lookup prevents collisions even when
    # legacy inventory has reused another department's prefix.
    prefix = department.code.split("-", 1)[0].upper()
    existing_codes = {
        code.casefold()
        for code in db.scalars(select(Bed.code).where(Bed.hospital_id == hospital.id))
    }
    suffixes: list[int] = []
    for bed_code in existing_codes:
        stem, separator, suffix = bed_code.partition("-")
        if separator and stem.casefold() == prefix.casefold() and suffix.isdigit():
            suffixes.append(int(suffix))
    number = max(suffixes, default=0) + 1

    created = 0
    while created < missing:
        code = f"{prefix}-{number:03d}"
        number += 1
        if code.casefold() in existing_codes:
            continue
        db.add(
            Bed(
                hospital_id=hospital.id,
                department_id=department.id,
                code=code,
                category="general",
                status="operational",
            )
        )
        existing_codes.add(code.casefold())
        created += 1
    db.flush()
    return created


def _seed_hospital_configuration(db: Session, spec: DemoHospital) -> dict[str, int | bool | str]:
    hospital = _find_hospital(db, spec)
    hospital_created = hospital is None
    if hospital is None:
        workspace = _get_or_create_workspace(db)
        hospital = Hospital(workspace_id=workspace.id, name=spec.name, code=spec.code,
                            available_to_users=False)
        db.add(hospital)
        db.flush()
    elif hospital.is_archived:
        raise DemoSeedConflict(f"{spec.name} is archived; restore it before seeding.")

    created_beds = 0
    departments_created = 0
    for name, code, capacity in spec.departments:
        existing = db.scalar(select(Department.id).where(
            Department.hospital_id == hospital.id, func.lower(Department.code) == code.lower(),
        ))
        department = _get_or_create_department(db, hospital, name, code, capacity)
        departments_created += int(existing is None)
        created_beds += _add_missing_beds(db, hospital, department)

    return {"name": spec.name, "code": spec.code, "hospital_created": hospital_created,
            "workspace_id": hospital.workspace_id,
            "hospital_id": hospital.id, "departments_created": departments_created,
            "beds_created": created_beds, "available_to_users": hospital.available_to_users}


def _atomic_seed(db: Session, specs: tuple[DemoHospital, ...]) -> list[dict[str, int | bool | str]]:
    try:
        # The CLI uses a fresh Session and gets one transaction. Callers that
        # already queried get a savepoint, so a partial multi-hospital seed
        # cannot leak changes if any later configuration conflicts.
        with (db.begin_nested() if db.in_transaction() else db.begin()):
            return [_seed_hospital_configuration(db, spec) for spec in specs]
    except IntegrityError as exc:
        raise DemoSeedConflict(
            "A concurrent or existing identifier conflicts with the demo seed; rerun after reviewing the hospital configuration."
        ) from exc


def seed_demo_hospital(db: Session) -> dict[str, int | bool | str]:
    """Create or complete Sunrise General Hospital (backward-compatible helper)."""
    return _atomic_seed(db, (DEMO_HOSPITALS[0],))[0]


def seed_demo_hospitals(db: Session) -> dict[str, int | list[dict[str, int | bool | str]]]:
    """Atomically create or complete all four fictional demo configurations."""
    results = _atomic_seed(db, DEMO_HOSPITALS)
    return {"hospitals_created": sum(bool(item["hospital_created"]) for item in results),
            "departments_created": sum(int(item["departments_created"]) for item in results),
            "beds_created": sum(int(item["beds_created"]) for item in results), "hospitals": results}


def main() -> int:
    initialize_database()
    db = SessionLocal()
    try:
        result = seed_demo_hospitals(db)
        for hospital in result["hospitals"]:
            total_beds = int(db.scalar(select(func.count(Bed.id)).where(
                Bed.hospital_id == int(hospital["hospital_id"]), Bed.status != "retired",
            )) or 0)
            print(f"Demo hospital ready: {hospital['name']} ({hospital['code']}); "
                  f"created {hospital['departments_created']} departments and {hospital['beds_created']} beds; "
                  f"current non-retired inventory {total_beds}; "
                  f"Available to users={str(hospital['available_to_users']).lower()}.")
        print("Publish each hospital from Hospital Management when an administrator is ready to expose it to users.")
        return 0
    except DemoSeedConflict as exc:
        print(f"Demo seed stopped safely: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
