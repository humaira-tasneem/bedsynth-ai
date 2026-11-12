from collections.abc import Generator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app
from app.routes import get_db


@pytest.fixture
def client(tmp_path) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "hospital-studio-test.db"
    test_engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def isolated_test_lifespan(_app):
        # Do not initialize or otherwise touch the configured user database in API tests.
        yield

    app.router.lifespan_context = isolated_test_lifespan
    with TestClient(app) as test_client:
        test_client.test_database_path = database_path
        yield test_client
    app.dependency_overrides.clear()
    app.router.lifespan_context = previous_lifespan
    test_engine.dispose()


def create_workspace(client: TestClient, name: str = "Workspace A") -> dict:
    response = client.post("/api/v1/workspaces", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def create_hospital(client: TestClient, workspace_id: int, name: str, code: str) -> dict:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/hospitals",
        json={"name": name, "code": code},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_hospital_create_list_retrieve_update_archive(client: TestClient) -> None:
    workspace = create_workspace(client)
    hospital = create_hospital(client, workspace["id"], "Harbor Simulation Hospital", "harbor-01")
    assert hospital["code"] == "HARBOR-01"
    assert hospital["workspace_id"] == workspace["id"]
    duplicate = client.post(
        f"/api/v1/workspaces/{workspace['id']}/hospitals",
        json={"name": "Different Facility", "code": "harbor-01"},
    )
    assert duplicate.status_code == 409

    listed = client.get(f"/api/v1/workspaces/{workspace['id']}/hospitals")
    assert [item["id"] for item in listed.json()] == [hospital["id"]]
    retrieved = client.get(f"/api/v1/workspaces/{workspace['id']}/hospitals/{hospital['id']}")
    assert retrieved.status_code == 200

    updated = client.patch(
        f"/api/v1/workspaces/{workspace['id']}/hospitals/{hospital['id']}",
        json={"name": "Harbor Demo Hospital"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Harbor Demo Hospital"

    archived = client.patch(
        f"/api/v1/workspaces/{workspace['id']}/hospitals/{hospital['id']}",
        json={"is_archived": True},
    )
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True
    assert client.get(f"/api/v1/workspaces/{workspace['id']}/hospitals").json() == []
    assert len(client.get(f"/api/v1/workspaces/{workspace['id']}/hospitals?include_archived=true").json()) == 1


def test_department_bed_relationship_capacity_and_duplicate_codes(client: TestClient) -> None:
    workspace = create_workspace(client)
    hospital = create_hospital(client, workspace["id"], "Cedar Test Hospital", "CEDAR")
    department_response = client.post(
        f"/api/v1/hospitals/{hospital['id']}/departments",
        json={"name": "General Medicine", "code": "med-1", "bed_capacity": 2},
    )
    assert department_response.status_code == 201
    department = department_response.json()
    assert department["code"] == "MED-1"
    assert client.get(f"/api/v1/hospitals/{hospital['id']}/departments").json()[0]["id"] == department["id"]

    bed_url = f"/api/v1/hospitals/{hospital['id']}/departments/{department['id']}/beds"
    bed_response = client.post(bed_url, json={"code": "b-01", "category": "general"})
    assert bed_response.status_code == 201
    assert bed_response.json()["hospital_id"] == hospital["id"]
    assert bed_response.json()["department_id"] == department["id"]

    duplicate_bed = client.post(bed_url, json={"code": "B-01"})
    assert duplicate_bed.status_code == 409
    second_bed = client.post(bed_url, json={"code": "B-02"})
    assert second_bed.status_code == 201
    updated_bed = client.patch(
        f"/api/v1/hospitals/{hospital['id']}/beds/{bed_response.json()['id']}",
        json={"category": "simulation", "status": "out_of_service"},
    )
    assert updated_bed.status_code == 200
    assert updated_bed.json()["category"] == "simulation"
    assert len(client.get(f"/api/v1/hospitals/{hospital['id']}/beds").json()) == 2
    over_capacity = client.post(bed_url, json={"code": "B-03"})
    assert over_capacity.status_code == 409

    duplicate_department = client.post(
        f"/api/v1/hospitals/{hospital['id']}/departments",
        json={"name": "Medicine Duplicate", "code": "MED-1", "bed_capacity": 2},
    )
    assert duplicate_department.status_code == 409

    capacity_reduction = client.patch(
        f"/api/v1/hospitals/{hospital['id']}/departments/{department['id']}",
        json={"bed_capacity": 1},
    )
    assert capacity_reduction.status_code == 409


def test_department_and_hospital_scope_are_validated(client: TestClient) -> None:
    workspace = create_workspace(client)
    first = create_hospital(client, workspace["id"], "Maple Demo Hospital", "MAPLE")
    second = create_hospital(client, workspace["id"], "Pine Demo Hospital", "PINE")
    department = client.post(
        f"/api/v1/hospitals/{first['id']}/departments",
        json={"name": "Observation", "code": "OBS", "bed_capacity": 2},
    ).json()

    wrong_hospital_bed = client.post(
        f"/api/v1/hospitals/{second['id']}/departments/{department['id']}/beds",
        json={"code": "P-1"},
    )
    assert wrong_hospital_bed.status_code == 404

    wrong_workspace_hospital = client.get(f"/api/v1/workspaces/{workspace['id'] + 999}/hospitals/{first['id']}")
    assert wrong_workspace_hospital.status_code == 404


def test_network_is_optional_and_must_belong_to_same_workspace(client: TestClient) -> None:
    first_workspace = create_workspace(client, "Workspace North")
    second_workspace = create_workspace(client, "Workspace South")
    network = client.post(
        f"/api/v1/workspaces/{first_workspace['id']}/networks",
        json={"name": "North Network"},
    ).json()
    independent = client.post(
        f"/api/v1/workspaces/{first_workspace['id']}/hospitals",
        json={"name": "Independent Demo Hospital", "code": "IND"},
    )
    assert independent.status_code == 201
    linked = client.post(
        f"/api/v1/workspaces/{first_workspace['id']}/hospitals",
        json={"name": "Network Demo Hospital", "code": "NET", "network_id": network["id"]},
    )
    assert linked.status_code == 201
    cross_workspace = client.post(
        f"/api/v1/workspaces/{second_workspace['id']}/hospitals",
        json={"name": "Invalid Network Hospital", "code": "BAD", "network_id": network["id"]},
    )
    assert cross_workspace.status_code == 422


def test_database_persists_after_client_session_restart(client: TestClient) -> None:
    workspace = create_workspace(client)
    hospital = create_hospital(client, workspace["id"], "Persistence Demo Hospital", "PERSIST")
    department = client.post(
        f"/api/v1/hospitals/{hospital['id']}/departments",
        json={"name": "Diagnostics", "code": "DIAG", "bed_capacity": 3},
    ).json()
    client.post(
        f"/api/v1/hospitals/{hospital['id']}/departments/{department['id']}/beds",
        json={"code": "D-1"},
    ).raise_for_status()

    # Read from a fresh engine/session as a backend restart would, not the request session.
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.models import Hospital as HospitalModel

    persisted_engine = create_engine(f"sqlite:///{client.test_database_path.as_posix()}")
    with Session(persisted_engine) as session:
        persisted = session.scalar(select(HospitalModel).where(HospitalModel.id == hospital["id"]))
        assert persisted is not None
        assert persisted.code == "PERSIST"
        assert persisted.departments[0].beds[0].code == "D-1"
    persisted_engine.dispose()


def test_bulk_bed_generation_creates_missing_beds_with_sequential_codes(client: TestClient) -> None:
    workspace = create_workspace(client)
    hospital = create_hospital(client, workspace["id"], "Sunrise Simulation Hospital", "SUNRISE")
    departments = []
    for code, capacity in (("EMG-01", 3), ("CAR-01", 2)):
        response = client.post(
            f"/api/v1/hospitals/{hospital['id']}/departments",
            json={"name": code, "code": code, "bed_capacity": capacity},
        )
        assert response.status_code == 201, response.text
        departments.append(response.json())

    preview = client.post(f"/api/v1/hospitals/{hospital['id']}/beds/generation-preview", json={})
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_to_create"] == 5
    assert [row["beds_to_create"] for row in preview.json()["departments"]] == [2, 3]

    generated = client.post(
        f"/api/v1/hospitals/{hospital['id']}/beds/generate",
        json={"preview_token": preview.json()["preview_token"], "confirmed": True},
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["beds_created"] == 5
    beds = client.get(f"/api/v1/hospitals/{hospital['id']}/beds").json()
    assert len(beds) == 5
    assert {bed["status"] for bed in beds} == {"operational"}
    assert {bed["code"] for bed in beds if bed["department_id"] == departments[0]["id"]} == {"EMG-001", "EMG-002", "EMG-003"}
    assert {bed["code"] for bed in beds if bed["department_id"] == departments[1]["id"]} == {"CAR-001", "CAR-002"}


def test_bulk_bed_generation_is_repeat_safe_and_respects_capacity(client: TestClient) -> None:
    workspace = create_workspace(client)
    hospital = create_hospital(client, workspace["id"], "Repeat Test Hospital", "REPEAT")
    department = client.post(
        f"/api/v1/hospitals/{hospital['id']}/departments",
        json={"name": "Emergency", "code": "EMG-01", "bed_capacity": 2},
    ).json()
    base = f"/api/v1/hospitals/{hospital['id']}"
    preview = client.post(f"{base}/beds/generation-preview", json={"department_ids": [department["id"]]}).json()
    first = client.post(f"{base}/beds/generate", json={"department_ids": [department["id"]], "preview_token": preview["preview_token"], "confirmed": True})
    assert first.status_code == 200, first.text
    assert first.json()["beds_created"] == 2

    repeat_preview = client.post(f"{base}/beds/generation-preview", json={"department_ids": [department["id"]]}).json()
    assert repeat_preview["total_to_create"] == 0
    repeat = client.post(f"{base}/beds/generate", json={"department_ids": [department["id"]], "preview_token": repeat_preview["preview_token"], "confirmed": True})
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["beds_created"] == 0
    assert len(client.get(f"{base}/beds").json()) == 2


def test_bulk_bed_generation_skips_existing_identifiers_and_rejects_stale_preview(client: TestClient) -> None:
    workspace = create_workspace(client)
    hospital = create_hospital(client, workspace["id"], "Duplicate Guard Hospital", "DUPGUARD")
    department = client.post(
        f"/api/v1/hospitals/{hospital['id']}/departments",
        json={"name": "Emergency", "code": "EMG-01", "bed_capacity": 4},
    ).json()
    base = f"/api/v1/hospitals/{hospital['id']}"
    bed_url = f"{base}/departments/{department['id']}/beds"
    assert client.post(bed_url, json={"code": "EMG-001"}).status_code == 201
    preview = client.post(f"{base}/beds/generation-preview", json={}).json()
    department_plan = preview["departments"][0]
    assert department_plan["beds_to_create"] == 3
    assert department_plan["first_bed_code"] == "EMG-002"

    # A normal CRUD write after preview invalidates the snapshot; no partial batch is written.
    assert client.post(bed_url, json={"code": "MANUAL-01"}).status_code == 201
    stale = client.post(f"{base}/beds/generate", json={"preview_token": preview["preview_token"], "confirmed": True})
    assert stale.status_code == 409
    assert len(client.get(f"{base}/beds").json()) == 2
    fresh_preview = client.post(f"{base}/beds/generation-preview", json={}).json()
    assert fresh_preview["departments"][0]["first_bed_code"] == "EMG-002"
    created = client.post(f"{base}/beds/generate", json={"preview_token": fresh_preview["preview_token"], "confirmed": True})
    assert created.status_code == 200, created.text
    codes = [bed["code"] for bed in client.get(f"{base}/beds").json()]
    assert len(codes) == len(set(codes)) == 4
    assert set(codes) == {"EMG-001", "EMG-002", "EMG-003", "MANUAL-01"}


def test_bulk_bed_generation_rejects_foreign_department(client: TestClient) -> None:
    workspace = create_workspace(client)
    first = create_hospital(client, workspace["id"], "First Simulation Hospital", "FIRST")
    second = create_hospital(client, workspace["id"], "Second Simulation Hospital", "SECOND")
    department = client.post(
        f"/api/v1/hospitals/{first['id']}/departments",
        json={"name": "Emergency", "code": "EMG", "bed_capacity": 2},
    ).json()
    response = client.post(
        f"/api/v1/hospitals/{second['id']}/beds/generation-preview",
        json={"department_ids": [department["id"]]},
    )
    assert response.status_code == 404
