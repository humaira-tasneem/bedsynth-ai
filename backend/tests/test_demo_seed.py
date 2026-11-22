from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker
from types import SimpleNamespace

from app import database
from app.models import Bed, Department, GenerationRun, Hospital, Workspace
from app.demo_seed import (
    DEMO_DEPARTMENTS,
    DEMO_HOSPITALS,
    DEMO_HOSPITAL_CODE,
    DEMO_HOSPITAL_NAME,
    seed_demo_hospital,
    seed_demo_hospitals,
)
from app.routes import list_hospitals


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
    assert hospital.workspace.name == "My workspace"

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
    workspace = Workspace(name="My workspace")
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
        select(func.count(Workspace.id)).where(Workspace.name == "My workspace")
    ) == 0


def test_all_four_demo_hospitals_have_expected_inventory_and_start_unpublished(seed_db: Session) -> None:
    result = seed_demo_hospitals(seed_db)
    default_workspace_id = seed_db.scalar(select(Workspace.id).where(Workspace.name == "My workspace"))
    assert default_workspace_id is not None

    assert result["hospitals_created"] == 4
    expected = {
        "SGH-001": ("Sunrise General Hospital", 5, 120),
        "CCH-001": ("CityCare Multispecialty Hospital", 7, 200),
        "GVCH-001": ("Green Valley Community Hospital", 4, 60),
        "ASH-001": ("Apex Specialty Hospital", 5, 100),
    }
    for code, (name, department_count, bed_count) in expected.items():
        hospital = seed_db.scalar(select(Hospital).where(Hospital.code == code))
        assert hospital is not None and hospital.name == name
        assert hospital.workspace_id == default_workspace_id
        assert hospital.available_to_users is False
        departments = list(seed_db.scalars(select(Department).where(Department.hospital_id == hospital.id)))
        assert len(departments) == department_count
        assert sum(seed_db.scalar(select(func.count(Bed.id)).where(
            Bed.department_id == department.id, Bed.status != "retired",
        )) for department in departments) == bed_count
        assert seed_db.scalar(select(func.count(Bed.id)).where(Bed.hospital_id == hospital.id)) == bed_count
    assert {hospital.code for hospital in seed_db.scalars(select(Hospital))} == set(expected)
    assert sum(item[2] for spec in DEMO_HOSPITALS for item in spec.departments) == 480


def test_admin_lists_all_demo_hospitals_while_users_only_see_published(seed_db: Session) -> None:
    seed_demo_hospitals(seed_db)
    workspace = seed_db.scalar(select(Workspace).where(Workspace.name == "My workspace"))
    sunrise = seed_db.scalar(select(Hospital).where(Hospital.code == "SGH-001"))
    sunrise.available_to_users = True
    seed_db.flush()

    admin_hospitals = list_hospitals(
        workspace_id=workspace.id, include_archived=True, db=seed_db,
        user=SimpleNamespace(role="admin"),
    )
    user_hospitals = list_hospitals(
        workspace_id=workspace.id, include_archived=True, db=seed_db,
        user=SimpleNamespace(role="user"),
    )

    assert {hospital.code for hospital in admin_hospitals} == {spec.code for spec in DEMO_HOSPITALS}
    assert [hospital.code for hospital in user_hospitals] == ["SGH-001"]


def test_multi_hospital_seed_is_repeat_safe_and_preserves_existing_sunrise_edits_and_runs(seed_db: Session) -> None:
    workspace = Workspace(name="My workspace")
    seed_db.add(workspace)
    seed_db.flush()
    sunrise = Hospital(workspace_id=workspace.id, name="Sunrise Admin Name", code="SGH-001",
                       available_to_users=True)
    seed_db.add(sunrise)
    seed_db.flush()
    edited_department = Department(hospital_id=sunrise.id, name="Cardiology Service", code="CAR-01",
                                   bed_capacity=25)
    seed_db.add(edited_department)
    seed_db.flush()
    existing_bed = Bed(hospital_id=sunrise.id, department_id=edited_department.id, code="CAR-001",
                       category="cardiac", status="out_of_service")
    run = GenerationRun(run_id="preserved-sunrise-run", workspace_id=workspace.id, hospital_id=sunrise.id,
                        owner_user_id=None, idempotency_key="preserved-sunrise-key",
                        config={"historical": "keep"}, seed=9, status="completed", patients_count=7)
    seed_db.add_all([existing_bed, run])
    seed_db.commit()

    first = seed_demo_hospitals(seed_db)
    seed_db.refresh(sunrise)
    seed_db.refresh(edited_department)
    seed_db.refresh(existing_bed)
    seed_db.refresh(run)
    assert sunrise.name == "Sunrise Admin Name" and sunrise.available_to_users is True
    assert edited_department.name == "Cardiology Service" and edited_department.bed_capacity == 25
    assert existing_bed.category == "cardiac" and existing_bed.status == "out_of_service"
    assert run.config == {"historical": "keep"} and run.patients_count == 7
    assert first["hospitals_created"] == 3

    second = seed_demo_hospitals(seed_db)
    assert second["hospitals_created"] == 0
    assert second["departments_created"] == 0
    assert second["beds_created"] == 0
    assert seed_db.scalar(select(func.count(Hospital.id))) == 4
    assert seed_db.scalar(select(func.count(GenerationRun.run_id)).where(
        GenerationRun.run_id == "preserved-sunrise-run",
    )) == 1


def test_multi_hospital_seed_recovers_a_partial_hospital_without_duplicates(seed_db: Session) -> None:
    workspace = Workspace(name="Partially seeded workspace")
    seed_db.add(workspace)
    seed_db.flush()
    citycare = Hospital(workspace_id=workspace.id, name="CityCare Admin Name", code="CCH-001",
                        available_to_users=True)
    seed_db.add(citycare)
    seed_db.flush()
    emergency = Department(hospital_id=citycare.id, name="Emergency Unit", code="EMG-01", bed_capacity=35)
    seed_db.add(emergency)
    seed_db.flush()
    seed_db.add_all(Bed(hospital_id=citycare.id, department_id=emergency.id,
                        code=f"EMG-{number:03d}", category="custom", status="operational")
                    for number in range(1, 4))
    seed_db.commit()

    first = seed_demo_hospitals(seed_db)
    second = seed_demo_hospitals(seed_db)
    citycare_beds = seed_db.scalar(select(func.count(Bed.id)).where(Bed.hospital_id == citycare.id))
    assert citycare_beds == 200
    assert seed_db.scalar(select(func.count(Department.id)).where(Department.hospital_id == citycare.id)) == 7
    assert seed_db.scalar(select(func.count(func.distinct(Bed.code))).where(Bed.hospital_id == citycare.id)) == 200
    assert first["hospitals_created"] == 3
    assert second["hospitals_created"] == 0 and second["departments_created"] == 0 and second["beds_created"] == 0
    seed_db.refresh(citycare)
    seed_db.refresh(emergency)
    assert citycare.name == "CityCare Admin Name" and citycare.available_to_users is True
    assert emergency.name == "Emergency Unit" and emergency.bed_capacity == 35


def test_seed_moves_runless_demo_hospitals_into_existing_my_workspace_without_configuration_changes(seed_db: Session) -> None:
    target = Workspace(name="My workspace")
    source = Workspace(name="BedSynth Demo Workspace")
    seed_db.add_all([target, source])
    seed_db.flush()
    expected_publication = {"CCH-001": True, "GVCH-001": False, "ASH-001": True}
    before = {}
    for spec in DEMO_HOSPITALS[1:]:
        hospital = Hospital(workspace_id=source.id, name=spec.name, code=spec.code,
                            available_to_users=expected_publication[spec.code])
        seed_db.add(hospital)
        seed_db.flush()
        for name, code, capacity in spec.departments:
            department = Department(hospital_id=hospital.id, name=name, code=code,
                                    bed_capacity=capacity)
            seed_db.add(department)
            seed_db.flush()
            for number in range(1, capacity + 1):
                seed_db.add(Bed(hospital_id=hospital.id, department_id=department.id,
                                code=f"{code.split('-')[0]}-{number:03d}",
                                category="custom", status="out_of_service" if number == 1 else "operational"))
        seed_db.flush()
        before[hospital.code] = {
            "id": hospital.id,
            "departments": [(department.id, department.code, department.name, department.bed_capacity)
                            for department in seed_db.scalars(select(Department).where(Department.hospital_id == hospital.id))],
            "beds": [(bed.id, bed.code, bed.category, bed.status)
                     for bed in seed_db.scalars(select(Bed).where(Bed.hospital_id == hospital.id))],
        }
    seed_db.commit()

    result = seed_demo_hospitals(seed_db)

    for code, original in before.items():
        hospital = seed_db.scalar(select(Hospital).where(Hospital.code == code))
        assert hospital.id == original["id"] and hospital.workspace_id == target.id
        assert hospital.available_to_users is expected_publication[code]
        assert [(department.id, department.code, department.name, department.bed_capacity)
                for department in seed_db.scalars(select(Department).where(Department.hospital_id == hospital.id))] == original["departments"]
        assert [(bed.id, bed.code, bed.category, bed.status)
                for bed in seed_db.scalars(select(Bed).where(Bed.hospital_id == hospital.id))] == original["beds"]
    assert result["hospitals_created"] == 1  # Only Sunrise was absent.
    assert seed_db.get(Workspace, source.id) is not None
    assert seed_db.scalar(select(func.count(Hospital.id)).where(Hospital.workspace_id == target.id)) == 4


def test_seed_refuses_workspace_move_when_it_would_reassign_historical_run_scope(seed_db: Session) -> None:
    target = Workspace(name="My workspace")
    source = Workspace(name="BedSynth Demo Workspace")
    seed_db.add_all([target, source])
    seed_db.flush()
    hospital = Hospital(workspace_id=source.id, name="CityCare Multispecialty Hospital", code="CCH-001")
    seed_db.add(hospital)
    seed_db.flush()
    run = GenerationRun(run_id="foreign-workspace-run", workspace_id=source.id,
                        hospital_id=hospital.id, owner_user_id=None,
                        idempotency_key="foreign-workspace-key", config={}, seed=5,
                        status="completed")
    seed_db.add(run)
    seed_db.commit()

    with pytest.raises(ValueError, match="historical generation runs in another workspace"):
        seed_demo_hospitals(seed_db)

    seed_db.refresh(hospital)
    assert hospital.workspace_id == source.id
    assert seed_db.get(GenerationRun, run.run_id) is not None
    assert seed_db.scalar(select(func.count(Hospital.id))) == 1


def test_multi_hospital_conflict_rolls_back_earlier_hospital_creations(seed_db: Session) -> None:
    workspace = Workspace(name="Existing Apex workspace")
    seed_db.add(workspace)
    seed_db.flush()
    apex = Hospital(workspace_id=workspace.id, name="Apex Specialty Hospital", code="ASH-001")
    seed_db.add(apex)
    seed_db.flush()
    over_capacity = Department(hospital_id=apex.id, name="Orthopedics", code="ORT-01", bed_capacity=1)
    seed_db.add(over_capacity)
    seed_db.flush()
    seed_db.add_all(Bed(hospital_id=apex.id, department_id=over_capacity.id,
                        code=f"ORT-{number:03d}", category="general", status="operational")
                    for number in (1, 2))
    seed_db.commit()

    with pytest.raises(ValueError, match="above its configured capacity"):
        seed_demo_hospitals(seed_db)

    assert {hospital.code for hospital in seed_db.scalars(select(Hospital))} == {"ASH-001"}
    assert seed_db.scalar(select(func.count(Department.id)).where(Department.hospital_id == apex.id)) == 1
    assert seed_db.scalar(select(func.count(Bed.id)).where(Bed.hospital_id == apex.id)) == 2
    assert seed_db.scalar(select(func.count(Workspace.id)).where(
        Workspace.name == "My workspace",
    )) == 0
