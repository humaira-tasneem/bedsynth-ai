"""Dataset library and export tests backed by temporary SQLite databases."""

import csv
import io
from collections.abc import Generator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app
from app.models import Admission, Bed, BedAssignment, BedTransfer, Discharge, GenerationRun, OccupancySnapshot, SyntheticPatient
from app.routes import get_db
from test_synthetic_generation import generation_config, make_hospital, preview_and_generate


@pytest.fixture
def dataset_client(tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'dataset-test.db').as_posix()}", connect_args={"check_same_thread": False})
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


def create_dataset(client, *, admissions=4, seed=17, workspace=None):
    if workspace is None:
        workspace_id, hospital_id, departments = make_hospital(client, department_count=2, beds_per_department=2)
    else:
        workspace_id = workspace
        hospital = client.post(f"/api/v1/workspaces/{workspace_id}/hospitals", json={"name": "Second Dataset Hospital", "code": "SECOND"}).json()
        departments = []
        for index in range(2):
            department = client.post(f"/api/v1/hospitals/{hospital['id']}/departments", json={"name": f"Second Department {index + 1}", "code": f"S-{index + 1}", "bed_capacity": 2}).json()
            departments.append(department)
            for number in range(1, 3):
                client.post(f"/api/v1/hospitals/{hospital['id']}/departments/{department['id']}/beds", json={"code": f"SB-{index + 1}-{number}"})
        hospital_id = hospital["id"]
    config = generation_config(departments, admissions=admissions, seed=seed)
    return workspace_id, hospital_id, departments, preview_and_generate(client, hospital_id, config)


def count_run_rows(client, run_id):
    models = (SyntheticPatient, Admission, Discharge, BedAssignment, BedTransfer, OccupancySnapshot)
    with client.test_sessions() as db:
        return {model.__tablename__: db.scalar(select(func.count()).select_from(model).where(model.run_id == run_id)) for model in models}


def test_workspace_dataset_library_supports_search_filter_sort_and_pagination(dataset_client):
    workspace_id, hospital_id, _, first = create_dataset(dataset_client, admissions=4, seed=11)
    second = preview_and_generate(dataset_client, hospital_id, generation_config(
        dataset_client.get(f"/api/v1/hospitals/{hospital_id}/departments").json(), admissions=2, seed=12,
    ))
    first_workspace_id, _, _, _ = create_dataset(dataset_client, admissions=1, seed=13)

    page = dataset_client.get(f"/api/v1/workspaces/{workspace_id}/datasets?page=1&page_size=1&sort=newest")
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 2
    assert page.json()["page"] == 1 and page.json()["page_size"] == 1 and page.json()["pages"] == 2
    assert page.json()["items"][0]["run_id"] == second["run_id"]
    assert page.json()["items"][0]["record_counts"]["admissions"] == 2
    assert dataset_client.get(f"/api/v1/workspaces/{workspace_id}/datasets?q={first['run_id'][:8]}").json()["total"] == 1
    assert dataset_client.get(f"/api/v1/workspaces/{workspace_id}/datasets?hospital_id={hospital_id}&status=completed").json()["total"] == 2
    assert dataset_client.get(f"/api/v1/workspaces/{first_workspace_id}/datasets").json()["total"] == 1
    assert dataset_client.get("/api/v1/workspaces/999999/datasets").status_code == 404
    assert dataset_client.get(f"/api/v1/workspaces/{workspace_id}/datasets?page=0").status_code == 422
    assert dataset_client.get(f"/api/v1/workspaces/{workspace_id}/datasets?page_size=101").status_code == 422


def test_dataset_detail_returns_actual_counts_departments_and_validation_history(dataset_client):
    _, hospital_id, departments, run = create_dataset(dataset_client)
    validation = dataset_client.post(f"/api/v1/generation-runs/{run['run_id']}/validations")
    assert validation.status_code == 201, validation.text
    response = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["hospital_id"] == hospital_id
    assert detail["hospital_name"] == "Fictional Generation Hospital"
    assert detail["record_counts"]["patients"] == 4
    assert detail["record_counts"]["admissions"] == 4
    assert detail["record_counts"]["discharges"] == run["discharges_count"]
    assert detail["record_counts"]["bed_transfers"] == run["transfers_count"]
    assert detail["record_counts"]["occupancy_snapshots"] == 6
    assert {row["department_id"] for row in detail["selected_departments"]} == {row["id"] for row in departments}
    assert detail["latest_validation"]["validation_id"] == validation.json()["validation_id"]
    assert detail["validation_reports"][0]["status"] == "passed"
    assert detail["analytics_summary"]["recorded_days"] == 3
    assert detail["analytics_summary"]["latest_snapshot_date"] is not None
    assert detail["analytics_summary"]["average_occupancy_pct"] is not None


def test_dataset_scenario_is_unavailable_when_legacy_run_has_no_scenario_metadata(dataset_client):
    workspace_id, _, _, run = create_dataset(dataset_client, admissions=1)
    with dataset_client.test_sessions() as db:
        stored_run = db.get(GenerationRun, run["run_id"])
        config = dict(stored_run.config)
        config.pop("scenario_name", None)
        request = dict(config["request"])
        request.pop("scenario", None)
        request.pop("patient_profile", None)
        config["request"] = request
        stored_run.config = config
        db.commit()

    listing = dataset_client.get(f"/api/v1/workspaces/{workspace_id}/datasets")
    assert listing.status_code == 200, listing.text
    assert listing.json()["items"][0]["scenario_name"] is None
    detail = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset")
    assert detail.status_code == 200, detail.text
    assert detail.json()["scenario_name"] is None
    assert "patient_profile" not in detail.json()["generation_config"]["request"]


def test_dataset_preview_paginates_and_returns_empty_entity_metadata(dataset_client):
    _, _, _, run = create_dataset(dataset_client, admissions=4)
    first = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/preview/patients?page=1&page_size=2")
    assert first.status_code == 200, first.text
    assert first.json()["total"] == 4 and first.json()["pages"] == 2
    assert len(first.json()["items"]) == 2
    assert first.json()["columns"][4] == {"key": "synthetic_patient_id", "label": "Synthetic Patient ID"}
    assert first.json()["items"][0]["run_id"] == run["run_id"]

    _, _, _, empty_run = create_dataset(dataset_client, admissions=0, seed=44)
    empty = dataset_client.get(f"/api/v1/generation-runs/{empty_run['run_id']}/dataset/preview/discharges")
    assert empty.status_code == 200
    assert empty.json()["items"] == [] and empty.json()["total"] == empty.json()["pages"] == 0
    assert empty.json()["columns"][0]["key"] == "id"


def test_csv_exports_have_stable_headers_values_and_proper_escaping(dataset_client):
    _, _, _, run = create_dataset(dataset_client, admissions=1)
    patient = dataset_client.test_sessions
    with patient() as db:
        record = db.scalar(select(SyntheticPatient).where(SyntheticPatient.run_id == run["run_id"]))
        record.synthetic_patient_id = 'SYN,"quoted"\nline'
        db.commit()

    response = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/export/patients")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="patients.csv"' in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
    assert rows[0] == ["id", "run_id", "workspace_id", "hospital_id", "synthetic_patient_id", "age_band", "age_years", "gender", "created_at"]
    assert rows[1][4] == 'SYN,"quoted"\nline'

    _, _, _, empty_run = create_dataset(dataset_client, admissions=0, seed=45)
    empty_csv = dataset_client.get(f"/api/v1/generation-runs/{empty_run['run_id']}/dataset/export/discharges")
    assert list(csv.reader(io.StringIO(empty_csv.content.decode("utf-8")))) == [["id", "run_id", "workspace_id", "hospital_id", "admission_id", "discharged_at"]]


def test_bed_inventory_export_is_generation_scoped_and_reports_generation_time_status(dataset_client):
    workspace_id, hospital_id, departments = make_hospital(dataset_client, department_count=2, beds_per_department=2)
    other_hospital = dataset_client.post(
        f"/api/v1/workspaces/{workspace_id}/hospitals",
        json={"name": "Unrelated Inventory Hospital", "code": "UNRELATED"},
    ).json()
    other_department = dataset_client.post(
        f"/api/v1/hospitals/{other_hospital['id']}/departments",
        json={"name": "Unrelated Department", "code": "OTHER-01", "bed_capacity": 1},
    ).json()
    dataset_client.post(
        f"/api/v1/hospitals/{other_hospital['id']}/departments/{other_department['id']}/beds",
        json={"code": "OTHER-BED"},
    )
    with dataset_client.test_sessions() as db:
        selected_beds = list(db.scalars(select(Bed).where(Bed.department_id == departments[0]["id"]).order_by(Bed.id)).all())
        selected_beds[0].status = "out_of_service"
        selected_beds[1].category = "critical_care"
        selected_bed_values = [{"id": bed.id, "code": bed.code, "status": bed.status} for bed in selected_beds]
        db.commit()

    config = generation_config(departments, admissions=1, seed=201)
    config["department_ids"] = [departments[0]["id"]]
    run = preview_and_generate(dataset_client, hospital_id, config)
    response = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/export/bed_inventory")
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert list(rows[0]) == [
        "run_id", "hospital_id", "bed_id", "bed_code", "department_id", "department_name",
        "bed_category", "bed_status", "generation_pool_member",
    ]
    assert len(rows) == 2
    assert {int(row["bed_id"]) for row in rows} == {bed["id"] for bed in selected_bed_values}
    assert {row["bed_code"] for row in rows} == {bed["code"] for bed in selected_bed_values}
    assert {int(row["department_id"]) for row in rows} == {departments[0]["id"]}
    assert {row["department_name"] for row in rows} == {departments[0]["name"]}
    assert {int(row["hospital_id"]) for row in rows} == {hospital_id}
    assert {row["run_id"] for row in rows} == {run["run_id"]}
    assert {row["bed_status"] for row in rows} == {"operational", "out_of_service"}
    assert {row["bed_category"] for row in rows} == {"general", "critical_care"}
    pool_members = {int(row["bed_id"]) for row in rows if row["generation_pool_member"] == "True"}
    assert pool_members == {bed["id"] for bed in selected_bed_values if bed["status"] == "operational"}

    manifest = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/manifest").json()
    inventory_file = next(item for item in manifest["exported_files"] if item["file"] == "bed_inventory.csv")
    assert inventory_file["status"] == "available"
    assert inventory_file["record_count"] == manifest["record_counts"]["bed_inventory"] == 2
    assert manifest["generation"]["selected_departments"] == [{
        "department_id": departments[0]["id"], "code": departments[0]["code"], "name": departments[0]["name"],
    }]


def test_empty_and_unavailable_historical_bed_inventory_are_distinguished(dataset_client):
    _, hospital_id, departments = make_hospital(dataset_client, department_count=1, beds_per_department=2, create_beds=False)
    empty_run = preview_and_generate(
        dataset_client,
        hospital_id,
        generation_config(departments, admissions=0, seed=202),
    )
    empty_csv = dataset_client.get(f"/api/v1/generation-runs/{empty_run['run_id']}/dataset/export/bed_inventory")
    empty_rows = list(csv.reader(io.StringIO(empty_csv.text)))
    assert empty_rows == [[
        "run_id", "hospital_id", "bed_id", "bed_code", "department_id", "department_name",
        "bed_category", "bed_status", "generation_pool_member",
    ]]
    empty_manifest = dataset_client.get(f"/api/v1/generation-runs/{empty_run['run_id']}/dataset/manifest").json()
    empty_file = next(item for item in empty_manifest["exported_files"] if item["file"] == "bed_inventory.csv")
    assert empty_file["status"] == "empty" and empty_file["record_count"] == 0
    assert empty_manifest["generation"]["bed_inventory_metadata"] == {"available": True, "record_count": 0}

    _, legacy_hospital_id, legacy_departments, legacy_run = create_dataset(dataset_client, admissions=1, seed=203)
    with dataset_client.test_sessions() as db:
        stored_run = db.get(GenerationRun, legacy_run["run_id"])
        legacy_config = dict(stored_run.config)
        legacy_config.pop("resolved_bed_inventory", None)
        legacy_config.pop("scenario_name", None)
        legacy_request = dict(legacy_config["request"])
        legacy_request.pop("scenario", None)
        legacy_request.pop("patient_profile", None)
        legacy_request.pop("length_of_stay_profile", None)
        legacy_request.pop("department_length_of_stay_profiles", None)
        legacy_config["request"] = legacy_request
        stored_run.config = legacy_config
        db.commit()
    unavailable_csv = dataset_client.get(f"/api/v1/generation-runs/{legacy_run['run_id']}/dataset/export/bed_inventory")
    assert list(csv.reader(io.StringIO(unavailable_csv.text))) == [empty_rows[0]]
    manifest = dataset_client.get(f"/api/v1/generation-runs/{legacy_run['run_id']}/dataset/manifest").json()
    inventory_file = next(item for item in manifest["exported_files"] if item["file"] == "bed_inventory.csv")
    assert inventory_file["status"] == "unavailable" and inventory_file["record_count"] is None
    assert manifest["record_counts"]["bed_inventory"] is None
    assert manifest["generation"]["bed_inventory_metadata"] == {"available": False, "record_count": None}
    assert manifest["generation"]["scenario"] is None
    assert manifest["generation"]["scenario_name"] is None
    assert manifest["generation"]["patient_profile"] is None
    assert manifest["generation"]["length_of_stay_profile"] is None
    assert manifest["generation"]["department_length_of_stay_profiles"] is None
    assert manifest["dataset_schema_version"] == "1.3.0"
    assert manifest["versions"]["schema"] == "1.3.0"
    assert manifest["versions"]["generation_config_schema"] is None
    assert manifest["generation"]["selected_departments"]
    assert manifest["hospital"]["hospital_id"] == legacy_hospital_id


def test_csv_exports_are_isolated_to_exact_generation_run(dataset_client):
    _, hospital_id, departments, first = create_dataset(dataset_client, admissions=2, seed=100)
    second = preview_and_generate(dataset_client, hospital_id, generation_config(departments, admissions=3, seed=101))
    first_rows = list(csv.DictReader(io.StringIO(dataset_client.get(f"/api/v1/generation-runs/{first['run_id']}/dataset/export/patients").text)))
    second_rows = list(csv.DictReader(io.StringIO(dataset_client.get(f"/api/v1/generation-runs/{second['run_id']}/dataset/export/patients").text)))
    assert len(first_rows) == 2 and all(row["run_id"] == first["run_id"] for row in first_rows)
    assert len(second_rows) == 3 and all(row["run_id"] == second["run_id"] for row in second_rows)


def test_manifest_contains_persisted_configuration_counts_versions_and_validations(dataset_client):
    _, hospital_id, departments, run = create_dataset(dataset_client)
    validation = dataset_client.post(f"/api/v1/generation-runs/{run['run_id']}/validations").json()
    response = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/manifest")
    assert response.status_code == 200
    assert 'attachment;' in response.headers["content-disposition"]
    manifest = response.json()
    assert manifest["application"]["name"] == "BedSynth AI"
    assert manifest["generation_run_id"] == run["run_id"]
    assert manifest["hospital"] == {"hospital_id": hospital_id, "hospital_name": "Fictional Generation Hospital"}
    assert manifest["generation"]["seed"] == run["seed"]
    assert manifest["generation"]["target_occupancy_pct"] == 50
    assert {row["department_id"] for row in manifest["generation"]["selected_departments"]} == {row["id"] for row in departments}
    assert manifest["record_counts"]["admissions"] == 4
    assert manifest["record_counts"]["bed_assignments"] > 0
    assert manifest["validation_reports"][0]["validation_id"] == validation["validation_id"]
    assert manifest["versions"]["generator"] == "deterministic-6"
    assert manifest["dataset_schema_version"] == "1.3.0"
    assert manifest["versions"]["schema"] == "1.3.0"
    assert manifest["versions"]["generation_config_schema"] is None
    assert manifest["reproducibility"]["reproducible"] is False
    assert "generation configuration schema version" in manifest["reproducibility"]["reason"]
    assert manifest["timestamp_convention"]["timezone"] == "UTC"
    assert manifest["generation"]["length_of_stay_profile"] == run["config"]["request"]["length_of_stay_profile"]
    assert manifest["generation"]["department_length_of_stay_profiles"] == []
    assert manifest["length_of_stay_semantics"]["unit"] == "days"
    assert "not a fabricated discharge" in manifest["length_of_stay_semantics"]["discharge"]
    assert "without applying a time shift" in manifest["timestamp_convention"]["serialization"]
    assert manifest["record_counts"]["bed_inventory"] == 4
    assert {item["file"] for item in manifest["exported_files"]} == {
        "patients.csv", "admissions.csv", "discharges.csv", "bed_assignments.csv",
        "bed_transfers.csv", "occupancy_snapshots.csv", "bed_inventory.csv", "waiting_queue.csv", "bed_turnaround.csv",
    }
    assert {relationship["child_file"] for relationship in manifest["relationships"]} >= {
        "admissions.csv", "discharges.csv", "bed_assignments.csv", "bed_transfers.csv",
        "occupancy_snapshots.csv", "waiting_queue.csv", "bed_turnaround.csv", "all CSV exports",
    }
    assert manifest["null_semantics"]["historical_metadata"]


def test_admissions_export_adds_versioned_arrival_fields_without_removing_legacy_columns(dataset_client):
    _, hospital_id, departments, run = create_dataset(dataset_client, admissions=5, seed=212)
    response = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/export/admissions")
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 5
    assert list(rows[0])[:9] == [
        "id", "run_id", "workspace_id", "hospital_id", "patient_id", "department_id",
        "initial_bed_id", "admitted_at", "status",
    ]
    assert list(rows[0])[9:] == ["admission_type", "requested_at", "scheduled_at", "bed_assigned_at"]
    assert all(row["run_id"] == run["run_id"] for row in rows)
    assert all(row["admission_type"] in {"planned", "emergency"} for row in rows)
    assert all(row["requested_at"] and row["bed_assigned_at"] for row in rows)
    for row in rows:
        if row["admission_type"] == "planned":
            assert row["scheduled_at"]
        else:
            assert row["scheduled_at"] == ""

    manifest = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/manifest").json()
    admission_file = next(item for item in manifest["exported_files"] if item["file"] == "admissions.csv")
    assert admission_file["record_count"] == 5
    assert "requested_at" in admission_file["description"] and "Historical rows" in admission_file["description"]
    assert manifest["dataset_schema_version"] == "1.3.0"
    assert manifest["generation"]["arrival_profile"] == run["config"]["request"]["arrival_profile"]
    assert manifest["admission_timestamp_semantics"]["bed_assigned_at"]
    assert manifest["timestamp_convention"]["timezone"] == "UTC"


def test_ongoing_stay_exports_preserve_csv_columns_and_manifest_semantics(dataset_client):
    _, hospital_id, departments = make_hospital(dataset_client, department_count=1, beds_per_department=1)
    config = generation_config(departments, admissions=1, seed=456)
    config.update({
        "start_date": "2025-01-01", "end_date": "2025-01-01", "target_occupancy_pct": 100,
        "length_of_stay_profile": {"distribution": "fixed", "minimum_days": 2, "mode_days": 2, "maximum_days": 2},
    })
    run = preview_and_generate(dataset_client, hospital_id, config)
    admissions_response = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/export/admissions")
    admission_rows = list(csv.DictReader(io.StringIO(admissions_response.text)))
    discharge_response = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/export/discharges")
    discharge_reader = csv.DictReader(io.StringIO(discharge_response.text))
    discharge_rows = list(discharge_reader)
    assignment_rows = list(csv.DictReader(io.StringIO(dataset_client.get(
        f"/api/v1/generation-runs/{run['run_id']}/dataset/export/bed_assignments",
    ).text)))
    assert len(admission_rows) == 1 and admission_rows[0]["status"] == "admitted"
    assert discharge_reader.fieldnames == ["id", "run_id", "workspace_id", "hospital_id", "admission_id", "discharged_at"]
    assert discharge_rows == []
    assert len(assignment_rows) == 1 and assignment_rows[0]["end_at"] == ""
    manifest = dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/manifest").json()
    assert manifest["dataset_schema_version"] == "1.3.0"
    assert manifest["generation"]["length_of_stay_profile"] == config["length_of_stay_profile"]
    assert manifest["length_of_stay_semantics"]["unit"] == "days"
    assert "right-censoring" in manifest["length_of_stay_semantics"]["discharge"]


def test_waiting_and_turnaround_exports_include_headers_counts_and_manifest(dataset_client):
    _, hospital_id, departments = make_hospital(dataset_client, department_count=1, beds_per_department=1)
    config = generation_config(departments, admissions=8, seed=5901)
    config.update({
        "start_date": "2025-03-01", "end_date": "2025-03-10", "target_occupancy_pct": 100,
        "length_of_stay_profile": {"distribution": "fixed", "minimum_days": 2, "mode_days": 2, "maximum_days": 2},
        "bed_turnaround_profile": {"distribution": "fixed", "minimum_hours": 2, "mode_hours": 2, "maximum_hours": 2},
        "waiting_queue": {"priority_policy": "emergency_first", "maximum_wait_hours": 168},
    })
    run = preview_and_generate(dataset_client, hospital_id, config)
    root = f"/api/v1/generation-runs/{run['run_id']}/dataset"
    queue = dataset_client.get(f"{root}/export/waiting_queue")
    turn = dataset_client.get(f"{root}/export/bed_turnaround")
    assert queue.status_code == turn.status_code == 200
    queue_rows = list(csv.DictReader(io.StringIO(queue.text)))
    turn_rows = list(csv.DictReader(io.StringIO(turn.text)))
    assert {"requested_at", "priority", "status", "waiting_duration_seconds", "outcome_reason"} <= set(queue_rows[0])
    assert {"assignment_id", "bed_id", "started_at", "completed_at", "duration_seconds"} <= set(turn_rows[0])
    assert len(queue_rows) == run["waiting_queue_count"]
    assert len(turn_rows) == run["bed_turnaround_count"]
    manifest = dataset_client.get(f"{root}/manifest").json()
    assert manifest["dataset_schema_version"] == "1.3.0"
    assert manifest["record_counts"]["waiting_queue"] == len(queue_rows)
    assert manifest["record_counts"]["bed_turnaround"] == len(turn_rows)
    assert manifest["waiting_queue_semantics"]["wait_duration"].startswith("bed_assigned_at minus requested_at")
    assert manifest["bed_turnaround_semantics"]["interval"].startswith("Half-open")


def test_historical_run_m4_events_are_unavailable_not_zero(dataset_client):
    workspace_id, hospital_id, _, run = create_dataset(dataset_client)
    with dataset_client.test_sessions() as db:
        legacy = db.get(GenerationRun, run["run_id"])
        legacy.waiting_queue_count = None
        legacy.bed_turnaround_count = None
        db.commit()
    root = f"/api/v1/generation-runs/{run['run_id']}/dataset"
    detail = dataset_client.get(root).json()
    assert detail["record_counts"]["waiting_queue"] is None
    assert detail["record_counts"]["bed_turnaround"] is None
    manifest = dataset_client.get(f"{root}/manifest").json()
    assert manifest["record_counts"]["waiting_queue"] is None
    assert manifest["record_counts"]["bed_turnaround"] is None
    assert dataset_client.get(f"{root}/export/waiting_queue").status_code == 409


def test_historical_admission_fields_export_as_unavailable_not_inferred(dataset_client):
    _, hospital_id, departments, run = create_dataset(dataset_client, admissions=1, seed=213)
    with dataset_client.test_sessions() as db:
        admission = db.scalar(select(Admission).where(Admission.run_id == run["run_id"]))
        admission.admission_type = None
        admission.requested_at = None
        admission.scheduled_at = None
        admission.bed_assigned_at = None
        db.commit()
    rows = list(csv.DictReader(io.StringIO(dataset_client.get(
        f"/api/v1/generation-runs/{run['run_id']}/dataset/export/admissions",
    ).text)))
    assert rows[0]["admission_type"] == ""
    assert rows[0]["requested_at"] == ""
    assert rows[0]["scheduled_at"] == ""
    assert rows[0]["bed_assigned_at"] == ""


def test_invalid_entities_missing_runs_and_read_only_operations(dataset_client):
    _, _, _, run = create_dataset(dataset_client)
    before = count_run_rows(dataset_client, run["run_id"])
    missing = "00000000-0000-0000-0000-000000000000"
    assert dataset_client.get(f"/api/v1/generation-runs/{missing}/dataset").status_code == 404
    assert dataset_client.get(f"/api/v1/generation-runs/{missing}/dataset/preview/patients").status_code == 404
    assert dataset_client.get(f"/api/v1/generation-runs/{missing}/dataset/manifest").status_code == 404
    assert dataset_client.get(f"/api/v1/generation-runs/{missing}/dataset/export/patients").status_code == 404
    assert dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/preview/not-an-entity").status_code == 422
    assert dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/export/not-an-entity").status_code == 422
    assert dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/preview/patients?page=0").status_code == 422
    assert dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/preview/patients?page_size=101").status_code == 422
    dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset")
    dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/preview/patients")
    dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/export/patients")
    dataset_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset/manifest")
    assert count_run_rows(dataset_client, run["run_id"]) == before
