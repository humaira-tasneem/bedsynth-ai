from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.main import app
from app.models import (
    Admission,
    Bed,
    BedAssignment,
    BedTransfer,
    Department,
    Discharge,
    GenerationRun,
    OccupancySnapshot,
    SyntheticPatient,
    utc_now,
)
from app.routes import get_db


@pytest.fixture
def generation_client(tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'generation-test.db').as_posix()}", connect_args={"check_same_thread": False})
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
        # Keep tests isolated from backend/bedsynth.db and its existing hospital records.
        yield

    old_lifespan = app.router.lifespan_context
    app.router.lifespan_context = isolated_lifespan
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        client.test_sessions = test_sessions
        yield client
    app.dependency_overrides.clear()
    app.router.lifespan_context = old_lifespan
    engine.dispose()


def make_hospital(client: TestClient, department_count: int = 2, beds_per_department: int = 2, create_beds: bool = True) -> tuple[int, int, list[dict]]:
    workspace = client.post("/api/v1/workspaces", json={"name": "Synthetic Test Workspace"}).json()
    hospital = client.post(
        f"/api/v1/workspaces/{workspace['id']}/hospitals",
        json={"name": "Fictional Generation Hospital", "code": "GEN-TEST"},
    ).json()
    departments = []
    for index in range(department_count):
        code = f"DPT-{index + 1:02d}"
        department = client.post(
            f"/api/v1/hospitals/{hospital['id']}/departments",
            json={"name": f"Simulation Department {index + 1}", "code": code, "bed_capacity": beds_per_department},
        ).json()
        departments.append(department)
        for bed_number in range(1, beds_per_department + 1) if create_beds else ():
            bed = client.post(
                f"/api/v1/hospitals/{hospital['id']}/departments/{department['id']}/beds",
                json={"code": f"{code}-{bed_number:03d}"},
            )
            assert bed.status_code == 201, bed.text
    return workspace["id"], hospital["id"], departments


def generation_config(departments: list[dict], *, admissions: int = 4, seed: int = 17, selected: bool = True) -> dict:
    return {
        "start_date": "2025-01-01",
        "end_date": "2025-01-03",
        "target_admissions": admissions,
        "target_occupancy_pct": 50 if admissions else 0,
        "seed": seed,
        "department_ids": [department["id"] for department in departments] if selected else None,
    }


def preview_and_generate(client: TestClient, hospital_id: int, config: dict, key: str | None = None) -> dict:
    preview_response = client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs/preview", json=config)
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    response = client.post(
        f"/api/v1/hospitals/{hospital_id}/generation-runs",
        json={**config, "idempotency_key": key or str(uuid4()), "preview_token": preview["preview_token"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_generation_creates_scoped_records_and_valid_occupancy(generation_client: TestClient) -> None:
    workspace_id, hospital_id, departments = make_hospital(generation_client)
    config = generation_config(departments)
    preview = generation_client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs/preview", json=config)
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_operational_beds"] == 4
    assert preview.json()["planned_peak_occupied_beds"] == 2

    run = preview_and_generate(generation_client, hospital_id, config)
    assert run["status"] == "completed", run.get("error_message")
    assert run["workspace_id"] == workspace_id
    assert run["hospital_id"] == hospital_id
    assert run["patients_count"] == run["admissions_count"] == run["discharges_count"] == 4
    assert run["snapshots_count"] == 6

    with generation_client.test_sessions() as db:
        patients = list(db.scalars(select(SyntheticPatient).where(SyntheticPatient.run_id == run["run_id"])).all())
        admissions = list(db.scalars(select(Admission).where(Admission.run_id == run["run_id"])).all())
        discharges = list(db.scalars(select(Discharge).where(Discharge.run_id == run["run_id"])).all())
        assignments = list(db.scalars(select(BedAssignment).where(BedAssignment.run_id == run["run_id"])).all())
        transfers = list(db.scalars(select(BedTransfer).where(BedTransfer.run_id == run["run_id"])).all())
        snapshots = list(db.scalars(select(OccupancySnapshot).where(OccupancySnapshot.run_id == run["run_id"])).all())
        assert all(patient.workspace_id == workspace_id and patient.hospital_id == hospital_id for patient in patients)
        assert all(admission.workspace_id == workspace_id and admission.hospital_id == hospital_id for admission in admissions)
        assert {admission.department_id for admission in admissions} == {department["id"] for department in departments}
        assert all(admission.status == "discharged" for admission in admissions)
        assert all(discharge.discharged_at > next(a.admitted_at for a in admissions if a.id == discharge.admission_id) for discharge in discharges)
        assert all(patient.age_band in {"0-17", "18-34", "35-49", "50-64", "65-79", "80+"} for patient in patients)
        assert all(patient.synthetic_patient_id.startswith("SYN-") for patient in patients)
        assert len({patient.synthetic_patient_id for patient in patients}) == 4
        assert len(transfers) > 0
        assert all(snapshot.available_beds == snapshot.operational_beds - snapshot.occupied_beds for snapshot in snapshots)
        assert all(snapshot.occupied_beds <= snapshot.operational_beds for snapshot in snapshots)
        assert all(snapshot.occupancy_pct == pytest.approx(snapshot.occupied_beds / snapshot.operational_beds * 100) for snapshot in snapshots)
        assert all(
            db.get(Bed, assignment.bed_id).hospital_id == assignment.hospital_id
            and db.get(Bed, assignment.bed_id).department_id == assignment.department_id
            for assignment in assignments
        )
        for group_key in ("bed_id", "admission_id"):
            grouped: dict[int, list[BedAssignment]] = {}
            for assignment in assignments:
                grouped.setdefault(getattr(assignment, group_key), []).append(assignment)
            for intervals in grouped.values():
                intervals.sort(key=lambda row: row.start_at)
                assert all(left.end_at <= right.start_at for left, right in zip(intervals, intervals[1:]))
        for transfer in transfers:
            source = next(row for row in assignments if row.admission_id == transfer.admission_id and row.bed_id == transfer.source_bed_id)
            destination = next(row for row in assignments if row.admission_id == transfer.admission_id and row.bed_id == transfer.destination_bed_id)
            discharge = next(row for row in discharges if row.admission_id == transfer.admission_id)
            admission = next(row for row in admissions if row.id == transfer.admission_id)
            assert source.end_at == transfer.transferred_at == destination.start_at
            assert admission.admitted_at < transfer.transferred_at < discharge.discharged_at


def test_generation_is_reproducible_and_idempotent(generation_client: TestClient) -> None:
    workspace_id, hospital_id, departments = make_hospital(generation_client)
    config = generation_config(departments, admissions=4, seed=2025)
    idempotency_key = str(uuid4())
    first_preview = generation_client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs/preview", json=config).json()
    request = {**config, "idempotency_key": idempotency_key, "preview_token": first_preview["preview_token"]}
    first = generation_client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs", json=request).json()
    repeated = generation_client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs", json=request).json()
    assert repeated["run_id"] == first["run_id"]

    second = preview_and_generate(generation_client, hospital_id, config)
    assert second["run_id"] != first["run_id"]
    with generation_client.test_sessions() as db:
        def comparable(run_id: str) -> dict:
            patients = list(db.execute(select(SyntheticPatient.synthetic_patient_id, SyntheticPatient.age_band).where(SyntheticPatient.run_id == run_id).order_by(SyntheticPatient.synthetic_patient_id)))
            admissions = list(db.execute(select(Admission.patient_id, Admission.department_id, Admission.initial_bed_id, Admission.admitted_at).where(Admission.run_id == run_id).order_by(Admission.patient_id)))
            transfers = list(db.execute(select(BedTransfer.admission_id, BedTransfer.source_bed_id, BedTransfer.destination_bed_id, BedTransfer.transferred_at).where(BedTransfer.run_id == run_id).order_by(BedTransfer.admission_id)))
            snapshots = list(db.execute(select(OccupancySnapshot.department_id, OccupancySnapshot.snapshot_at, OccupancySnapshot.occupied_beds).where(OccupancySnapshot.run_id == run_id).order_by(OccupancySnapshot.department_id, OccupancySnapshot.snapshot_at)))
            return {"patients": patients, "admissions": admissions, "transfers": transfers, "snapshots": snapshots}

        first_records = comparable(first["run_id"])
        second_records = comparable(second["run_id"])
        assert first_records["patients"] == second_records["patients"]
        assert first_records["snapshots"] == second_records["snapshots"]
        # Internal row IDs differ between runs; compare admission times and bed placements by index.
        assert [(row[1], row[2], row[3]) for row in first_records["admissions"]] == [(row[1], row[2], row[3]) for row in second_records["admissions"]]
        assert len(first_records["transfers"]) == len(second_records["transfers"])
        assert db.scalar(select(func.count(GenerationRun.run_id)).where(GenerationRun.workspace_id == workspace_id)) == 2


def test_generation_supports_selected_departments_and_rejects_bad_scope(generation_client: TestClient) -> None:
    _, hospital_id, departments = make_hospital(generation_client)
    config = generation_config(departments, admissions=2)
    config["department_ids"] = [departments[1]["id"]]
    run = preview_and_generate(generation_client, hospital_id, config)
    with generation_client.test_sessions() as db:
        assert db.scalar(select(func.count(Admission.id)).where(Admission.run_id == run["run_id"], Admission.department_id == departments[1]["id"])) == 2
        assert db.scalar(select(func.count(Admission.id)).where(Admission.run_id == run["run_id"], Admission.department_id == departments[0]["id"])) == 0

    foreign_workspace = generation_client.post("/api/v1/workspaces", json={"name": "Other Workspace"}).json()
    foreign_hospital = generation_client.post(f"/api/v1/workspaces/{foreign_workspace['id']}/hospitals", json={"name": "Other Hospital", "code": "OTHER"}).json()
    response = generation_client.post(f"/api/v1/hospitals/{foreign_hospital['id']}/generation-runs/preview", json={**config, "department_ids": [departments[0]["id"]]})
    assert response.status_code == 404


def test_generation_uses_only_operational_beds(generation_client: TestClient) -> None:
    _, hospital_id, departments = make_hospital(generation_client, department_count=1, beds_per_department=2)
    hospital_beds = generation_client.get(f"/api/v1/hospitals/{hospital_id}/beds").json()
    unavailable_bed = hospital_beds[0]
    update = generation_client.patch(
        f"/api/v1/hospitals/{hospital_id}/beds/{unavailable_bed['id']}",
        json={"status": "out_of_service"},
    )
    assert update.status_code == 200

    config = generation_config(departments, admissions=4)
    config["target_occupancy_pct"] = 100
    preview = generation_client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs/preview", json=config)
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_operational_beds"] == 1
    run = preview_and_generate(generation_client, hospital_id, config)
    with generation_client.test_sessions() as db:
        assignments = list(db.scalars(select(BedAssignment).where(BedAssignment.run_id == run["run_id"])).all())
        assert assignments
        assert {assignment.bed_id for assignment in assignments} == {hospital_beds[1]["id"]}


def test_generation_validation_and_zero_bed_handling(generation_client: TestClient) -> None:
    _, hospital_id, departments = make_hospital(generation_client, department_count=1, beds_per_department=2, create_beds=False)
    invalid = generation_config(departments, admissions=2)
    reversed_dates = {**invalid, "start_date": "2025-01-04"}
    assert generation_client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs/preview", json=reversed_dates).status_code == 422
    no_beds = generation_client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs/preview", json=invalid)
    assert no_beds.status_code == 409
    no_admissions = generation_config(departments, admissions=0)
    no_admissions["department_ids"] = [departments[0]["id"]]
    no_admissions["target_occupancy_pct"] = 0
    preview = generation_client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs/preview", json=no_admissions)
    assert preview.status_code == 200
    run = preview_and_generate(generation_client, hospital_id, no_admissions)
    with generation_client.test_sessions() as db:
        snapshots = list(db.scalars(select(OccupancySnapshot).where(OccupancySnapshot.run_id == run["run_id"])).all())
        assert len(snapshots) == 3
        assert all(snapshot.occupancy_pct is None for snapshot in snapshots)


def test_failed_generation_rolls_back_rows_and_persists_run_failure(generation_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, hospital_id, departments = make_hospital(generation_client, department_count=1, beds_per_department=2)
    config = generation_config(departments, admissions=2)
    preview = generation_client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs/preview", json=config).json()
    import app.services.synthetic_generation as generation_service

    def fail_after_partial_write(db, run, _config, _departments, _beds):
        db.add(SyntheticPatient(
            run_id=run.run_id,
            workspace_id=run.workspace_id,
            hospital_id=run.hospital_id,
            synthetic_patient_id="SYN-FAULT-INJECTION",
            age_band="18-34",
            created_at=utc_now(),
        ))
        db.flush()
        raise RuntimeError("injected test failure")

    monkeypatch.setattr(generation_service, "_write_generation_data", fail_after_partial_write)
    failed = generation_client.post(
        f"/api/v1/hospitals/{hospital_id}/generation-runs",
        json={**config, "idempotency_key": str(uuid4()), "preview_token": preview["preview_token"]},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"
    assert "injected test failure" in failed.json()["error_message"]
    with generation_client.test_sessions() as db:
        run_id = failed.json()["run_id"]
        assert db.scalar(select(func.count(SyntheticPatient.id)).where(SyntheticPatient.run_id == run_id)) == 0
        assert db.scalar(select(func.count(Admission.id)).where(Admission.run_id == run_id)) == 0


def test_generation_history_is_workspace_scoped(generation_client: TestClient) -> None:
    workspace_id, hospital_id, departments = make_hospital(generation_client, department_count=1, beds_per_department=1)
    config = generation_config(departments, admissions=1)
    preview_and_generate(generation_client, hospital_id, config)
    history = generation_client.get(f"/api/v1/workspaces/{workspace_id}/generation-runs?hospital_id={hospital_id}")
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["hospital_id"] == hospital_id
