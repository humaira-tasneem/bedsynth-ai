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
from app.models import Admission, BedAssignment, BedTransfer, Discharge, OccupancySnapshot, SyntheticPatient
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
    assert detail["record_counts"]["discharges"] == 4
    assert detail["record_counts"]["bed_transfers"] == run["transfers_count"]
    assert detail["record_counts"]["occupancy_snapshots"] == 6
    assert {row["department_id"] for row in detail["selected_departments"]} == {row["id"] for row in departments}
    assert detail["latest_validation"]["validation_id"] == validation.json()["validation_id"]
    assert detail["validation_reports"][0]["status"] == "passed"
    assert detail["analytics_summary"]["recorded_days"] == 3
    assert detail["analytics_summary"]["latest_snapshot_date"] is not None
    assert detail["analytics_summary"]["average_occupancy_pct"] is not None


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
    assert rows[0] == ["id", "run_id", "workspace_id", "hospital_id", "synthetic_patient_id", "age_band", "created_at"]
    assert rows[1][4] == 'SYN,"quoted"\nline'

    _, _, _, empty_run = create_dataset(dataset_client, admissions=0, seed=45)
    empty_csv = dataset_client.get(f"/api/v1/generation-runs/{empty_run['run_id']}/dataset/export/discharges")
    assert list(csv.reader(io.StringIO(empty_csv.content.decode("utf-8")))) == [["id", "run_id", "workspace_id", "hospital_id", "admission_id", "discharged_at"]]


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
    assert manifest["versions"]["generator"] == "deterministic-1"
    assert manifest["versions"]["schema"] is None
    assert manifest["reproducibility"]["reproducible"] is False
    assert "schema version" in manifest["reproducibility"]["reason"]


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
