from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app import database
from app.models import Bed, Department, GenerationRun, Hospital, Workspace
from app.demo_seed import DEMO_DEPARTMENTS, DEMO_HOSPITAL_CODE, DEMO_HOSPITAL_NAME, seed_demo_hospital


@pytest.fixture
def seed_db(tmp_path, monkeypatch) -> Generator[Session, None, None]:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'demo-seed.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database, "engine", engine)
    database.initialize_database()
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        yield db
    engine.dispose()


def _hospital(db: Session) -> Hospital:
    return db.scalar(select(Hospital).where(Hospital.code == DEMO_HOSPITAL_CODE))


def test_fresh_database_initialization_and_first_seed_create_unpublished_120_beds(seed_db: Session) -> None:
    tables = set(inspect(seed_db.get_bind()).get_table_names())
    assert {"workspaces", "hospitals", "departments", "beds", "generation_runs"} <= tables

    result = seed_demo_hospital(seed_db)
    hospital = _hospital(seed_db)
    assert result["departments_created"] == 5
    assert result["beds_created"] == 120
    assert hospital.name == DEMO_HOSPITAL_NAME
    assert hospital.code == DEMO_HOSPITAL_CODE
    assert hospital.available_to_users is False
    assert hospital.workspace.name == "BedSynth Demo Workspace"

    departments = list(
        seed_db.scalars(select(Department).where(Department.hospital_id == hospital.id))
    )
    expected = {code: (name, capacity) for name, code, capacity in DEMO_DEPARTMENTS}
    assert {department.code: (department.name, department.bed_capacity) for department in departments} == expected
    counts = {
        department.code: seed_db.scalar(
            select(func.count(Bed.id)).where(
                Bed.department_id == department.id,
                Bed.status != "retired",
            )
        )
        for department in departments
    }
    assert counts == {code: capacity for name, code, capacity in DEMO_DEPARTMENTS}
    assert sum(counts.values()) == 120
    assert seed_db.scalar(select(func.count(Bed.id)).where(Bed.hospital_id == hospital.id)) == 120


def test_repeated_seed_is_idempotent_and_bed_identifiers_are_unique(seed_db: Session) -> None:
    first = seed_demo_hospital(seed_db)
    second = seed_demo_hospital(seed_db)
    hospital_id = int(first["hospital_id"])

    assert second["departments_created"] == 0
    assert second["beds_created"] == 0
    assert seed_db.scalar(select(func.count(Hospital.id)).where(Hospital.code == DEMO_HOSPITAL_CODE)) == 1
    assert seed_db.scalar(select(func.count(Department.id)).where(Department.hospital_id == hospital_id)) == 5
    assert seed_db.scalar(select(func.count(Bed.id)).where(Bed.hospital_id == hospital_id)) == 120
    assert seed_db.scalar(
        select(func.count(func.distinct(Bed.code))).where(Bed.hospital_id == hospital_id)
    ) == 120


def test_seed_fills_partial_configuration_to_current_department_capacities(seed_db: Session) -> None:
    workspace = Workspace(name="Existing workspace")
    seed_db.add(workspace)
    seed_db.flush()
    hospital = Hospital(workspace_id=workspace.id, name=DEMO_HOSPITAL_NAME, code=DEMO_HOSPITAL_CODE)
    seed_db.add(hospital)
    seed_db.flush()
    emergency = Department(hospital_id=hospital.id, code="EMG-01", name="Emergency", bed_capacity=20)
    seed_db.add(emergency)
    seed_db.flush()
    seed_db.add_all(
        Bed(
            hospital_id=hospital.id,
            department_id=emergency.id,
            code=f"EMG-{number:03d}",
            status="operational",
            category="general",
        )
        for number in range(1, 4)
    )
    seed_db.commit()

    result = seed_demo_hospital(seed_db)

    assert result["departments_created"] == 4
    assert result["beds_created"] == 117
    assert seed_db.scalar(select(func.count(Bed.id)).where(Bed.department_id == emergency.id)) == 20
    assert seed_db.scalar(select(func.count(Bed.id)).where(Bed.hospital_id == hospital.id)) == 120
    assert seed_db.scalar(
        select(func.count(func.distinct(Bed.code))).where(Bed.hospital_id == hospital.id)
    ) == 120


def test_seed_preserves_administrator_changes_and_historical_generation_run(seed_db: Session) -> None:
    workspace = Workspace(name="Admin workspace")
    seed_db.add(workspace)
    seed_db.flush()
    hospital = Hospital(
        workspace_id=workspace.id,
        name=DEMO_HOSPITAL_NAME,
        code=DEMO_HOSPITAL_CODE,
        available_to_users=True,
    )
    seed_db.add(hospital)
    seed_db.flush()
    edited_department = Department(
        hospital_id=hospital.id,
        name="Cardiology Unit",
        code="CAR-01",
        bed_capacity=26,
    )
    seed_db.add(edited_department)
    seed_db.flush()
    existing_bed = Bed(
        hospital_id=hospital.id,
        department_id=edited_department.id,
        code="CAR-001",
        status="out_of_service",
        category="critical-care",
    )
    run = GenerationRun(
        run_id="historical-demo-seed-run",
        workspace_id=workspace.id,
        hospital_id=hospital.id,
        owner_user_id=None,
        idempotency_key="historical-demo-seed-key",
        config={"historical": True},
        seed=41,
        status="completed",
    )
    seed_db.add_all([existing_bed, run])
    seed_db.commit()

    result = seed_demo_hospital(seed_db)

    seed_db.refresh(hospital)
    seed_db.refresh(edited_department)
    seed_db.refresh(existing_bed)
    assert hospital.name == DEMO_HOSPITAL_NAME
    assert hospital.available_to_users is True
    assert edited_department.name == "Cardiology Unit"
    assert edited_department.bed_capacity == 26
    assert existing_bed.status == "out_of_service"
    assert existing_bed.category == "critical-care"
    assert result["beds_created"] == 120  # 25 new in Cardiology plus the other 95.
    assert seed_db.get(GenerationRun, "historical-demo-seed-run") is not None


def test_over_capacity_partial_configuration_rolls_back_all_seed_changes(seed_db: Session) -> None:
    workspace = Workspace(name="Partial workspace")
    seed_db.add(workspace)
    seed_db.flush()
    hospital = Hospital(workspace_id=workspace.id, name=DEMO_HOSPITAL_NAME, code=DEMO_HOSPITAL_CODE)
    seed_db.add(hospital)
    seed_db.flush()
    last_department = Department(
        hospital_id=hospital.id,
        name="Orthopedics",
        code="ORT-01",
        bed_capacity=1,
    )
    seed_db.add(last_department)
    seed_db.flush()
    seed_db.add_all(
        Bed(
            hospital_id=hospital.id,
            department_id=last_department.id,
            code=f"ORT-{number:03d}",
            category="general",
            status="operational",
        )
        for number in (1, 2)
    )
    seed_db.commit()
    counts_before = (
        seed_db.scalar(select(func.count(Department.id)).where(Department.hospital_id == hospital.id)),
        seed_db.scalar(select(func.count(Bed.id)).where(Bed.hospital_id == hospital.id)),
    )

    with pytest.raises(ValueError, match="above its configured capacity"):
        seed_demo_hospital(seed_db)

    counts_after = (
        seed_db.scalar(select(func.count(Department.id)).where(Department.hospital_id == hospital.id)),
        seed_db.scalar(select(func.count(Bed.id)).where(Bed.hospital_id == hospital.id)),
    )
    assert counts_after == counts_before == (1, 2)
    assert seed_db.scalar(
        select(func.count(Workspace.id)).where(Workspace.name == "BedSynth Demo Workspace")
    ) == 0
