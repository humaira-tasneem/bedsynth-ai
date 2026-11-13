"""Validation API tests use the generation suite's isolated temporary database fixture."""

from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app
from app.models import Admission, BedAssignment, BedTransfer, Department, Discharge, GenerationRun, OccupancySnapshot, SyntheticPatient
from app.routes import get_db
from test_synthetic_generation import generation_config, make_hospital, preview_and_generate


@pytest.fixture
def generation_client(tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'validation-test.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    test_sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_db():
        db = test_sessions()
        try:
            yield db
        finally:
            db.close()

    @asynccontextmanager
    async def isolated_lifespan(_app):
        yield

    previous_lifespan = app.router.lifespan_context
    app.router.lifespan_context = isolated_lifespan
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            client.test_sessions = test_sessions
            yield client
    finally:
        app.dependency_overrides.clear()
        app.router.lifespan_context = previous_lifespan
        engine.dispose()


def create_valid_run(client):
    _, hospital_id, departments = make_hospital(client, department_count=2, beds_per_department=3)
    run = preview_and_generate(client, hospital_id, generation_config(departments, admissions=4, seed=741))
    return hospital_id, departments, run


def validate(client, run_id):
    response = client.post(f"/api/v1/generation-runs/{run_id}/validations")
    assert response.status_code == 201, response.text
    return response.json()


def test_valid_generated_run_scores_100_and_is_read_only(generation_client):
    _, _, run = create_valid_run(generation_client)
    with generation_client.test_sessions() as db:
        before = {
            model.__tablename__: db.scalar(select(func.count()).select_from(model).where(model.run_id == run["run_id"]))
            for model in (SyntheticPatient, Admission, BedAssignment, BedTransfer, OccupancySnapshot)
        }
    report = validate(generation_client, run["run_id"])
    assert report["score"] == 100
    assert report["checks_failed"] == report["warning_count"] == 0
    assert report["status"] == "passed"
    assert all(category["checks_failed"] == 0 for category in report["categories"])
    with generation_client.test_sessions() as db:
        after = {
            model.__tablename__: db.scalar(select(func.count()).select_from(model).where(model.run_id == run["run_id"]))
            for model in (SyntheticPatient, Admission, BedAssignment, BedTransfer, OccupancySnapshot)
        }
        assert before == after
        assert db.get(GenerationRun, run["run_id"]).status == "completed"


def test_validation_reports_are_persisted_and_listed_in_history(generation_client):
    _, _, run = create_valid_run(generation_client)
    first = validate(generation_client, run["run_id"])
    second = validate(generation_client, run["run_id"])
    history = generation_client.get(f"/api/v1/generation-runs/{run['run_id']}/validations")
    assert history.status_code == 200
    assert {row["validation_id"] for row in history.json()} == {first["validation_id"], second["validation_id"]}
    detail = generation_client.get(f"/api/v1/validations/{first['validation_id']}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run["run_id"]


def test_overlap_and_snapshot_corruption_are_reported_and_cap_critical_score(generation_client):
    _, _, run = create_valid_run(generation_client)
    with generation_client.test_sessions() as db:
        first = db.scalar(select(BedAssignment).where(BedAssignment.run_id == run["run_id"]))
        db.add(BedAssignment(run_id=first.run_id, workspace_id=first.workspace_id, hospital_id=first.hospital_id,
                             admission_id=first.admission_id, department_id=first.department_id, bed_id=first.bed_id,
                             start_at=first.start_at + timedelta(minutes=1), end_at=first.end_at))
        snap = db.scalar(select(OccupancySnapshot).where(OccupancySnapshot.run_id == run["run_id"]))
        snap.occupied_beds = snap.occupied_beds + 1
        snap.available_beds = snap.operational_beds - snap.occupied_beds
        db.commit()
    report = validate(generation_client, run["run_id"])
    assert report["score"] <= 49
    assert report["status"] == "failed"
    assert {issue["code"] for issue in report["issues"]} & {"assignment_overlap", "snapshot_from_assignments"}


def test_capacity_violation_and_invalid_transfer_are_reported(generation_client):
    _, departments, run = create_valid_run(generation_client)
    with generation_client.test_sessions() as db:
        department = db.get(Department, departments[0]["id"])
        department.bed_capacity = 1
        transfer = db.scalar(select(BedTransfer).where(BedTransfer.run_id == run["run_id"]))
        # A transfer outside the linked encounter remains representable in the DB and must be flagged.
        transfer.transferred_at = transfer.transferred_at + timedelta(days=30)
        db.commit()
    report = validate(generation_client, run["run_id"])
    codes = {issue["code"] for issue in report["issues"]}
    assert "configured_department_capacity" in codes
    assert "transfer_timestamp_order" in codes


def test_validation_rejects_unknown_or_incomplete_runs(generation_client):
    assert generation_client.post("/api/v1/generation-runs/missing/validations").status_code == 404
    _, hospital_id, departments = make_hospital(generation_client)
    run = preview_and_generate(generation_client, hospital_id, generation_config(departments, admissions=0))
    assert run["status"] == "completed"
    # Zero-admission generations are valid (and provide a safe zero-operational denominator case).
    report = validate(generation_client, run["run_id"])
    assert report["score"] == 100
    assert report["issues"] == []


def test_missing_patient_relationship_is_reported(generation_client):
    _, _, run = create_valid_run(generation_client)
    engine = generation_client.test_sessions.kw["bind"]
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql(
            "UPDATE admissions SET patient_id = 999999 WHERE id = "
            "(SELECT id FROM admissions WHERE run_id = ? LIMIT 1)", (run["run_id"],)
        )
        connection.commit()
    report = validate(generation_client, run["run_id"])
    assert "admission_patient" in {issue["code"] for issue in report["issues"]}


def test_duplicate_synthetic_identifiers_are_rejected_by_persisted_constraint(generation_client):
    _, _, run = create_valid_run(generation_client)
    with generation_client.test_sessions() as db:
        patient = db.scalar(select(SyntheticPatient).where(SyntheticPatient.run_id == run["run_id"]))
        duplicate = SyntheticPatient(run_id=patient.run_id, workspace_id=patient.workspace_id, hospital_id=patient.hospital_id,
                                     synthetic_patient_id=patient.synthetic_patient_id, age_band=patient.age_band)
        db.add(duplicate)
        try:
            db.commit()
            assert False, "The per-run synthetic patient identifier constraint should reject duplicates."
        except IntegrityError:
            db.rollback()
    report = validate(generation_client, run["run_id"])
    assert report["score"] == 100


def test_invalid_admission_discharge_timestamps_are_reported(generation_client):
    _, _, run = create_valid_run(generation_client)
    with generation_client.test_sessions() as db:
        admission = db.scalar(select(Admission).where(Admission.run_id == run["run_id"]))
        discharge = db.scalar(select(Discharge).where(Discharge.admission_id == admission.id))
        discharge.discharged_at = admission.admitted_at - timedelta(hours=1)
        db.commit()
    report = validate(generation_client, run["run_id"])
    assert "admission_discharge_order" in {issue["code"] for issue in report["issues"]}


def test_zero_operational_beds_use_null_occupancy_percent(generation_client):
    _, hospital_id, departments = make_hospital(generation_client, department_count=1, beds_per_department=2, create_beds=False)
    run = preview_and_generate(generation_client, hospital_id, generation_config(departments, admissions=0))
    report = validate(generation_client, run["run_id"])
    assert report["score"] == 100
    with generation_client.test_sessions() as db:
        snapshots = list(db.scalars(select(OccupancySnapshot).where(OccupancySnapshot.run_id == run["run_id"])).all())
        assert snapshots and all(row.operational_beds == 0 and row.occupancy_pct is None for row in snapshots)
