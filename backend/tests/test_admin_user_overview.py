"""Read-only administrator account and generation metadata endpoints."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import create_session, hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Department, GenerationRun, Hospital, User, Workspace


@pytest.fixture
def overview_client(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'admin-overview.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    @asynccontextmanager
    async def isolated_lifespan(_app):
        yield

    old_lifespan = app.router.lifespan_context
    app.router.lifespan_context = isolated_lifespan
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            client.test_sessions = sessions
            yield client
    finally:
        app.dependency_overrides.clear()
        app.router.lifespan_context = old_lifespan
        engine.dispose()


def seed(overview_client):
    with overview_client.test_sessions() as db:
        admin = User(email="admin@overview.test", password_hash=hash_password("admin-password-123"), role="admin")
        user = User(email="researcher@overview.test", password_hash=hash_password("user-password-123"), role="user")
        workspace = Workspace(name="Overview workspace")
        db.add_all([admin, user, workspace]); db.flush()
        hospital = Hospital(workspace_id=workspace.id, name="Overview Hospital", code="OVH")
        db.add(hospital); db.flush()
        department = Department(hospital_id=hospital.id, name="Cardiology", code="CAR", bed_capacity=3)
        db.add(department); db.flush()
        def run(run_id, owner_id, *, guest_id=None, deleted_at=None):
            return GenerationRun(
                run_id=run_id, workspace_id=workspace.id, hospital_id=hospital.id,
                owner_user_id=owner_id, guest_session_id=guest_id, deleted_at=deleted_at,
                idempotency_key=f"00000000-0000-0000-0000-{run_id[-12:]}",
                config={"request": {"scenario": "normal_operations", "start_date": "2026-01-01",
                                     "end_date": "2026-01-02", "target_admissions": 2,
                                     "target_occupancy_pct": 50},
                        "scenario_name": "Normal Operations", "resolved_department_ids": [department.id]},
                seed=1234, status="completed", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc), patients_count=2,
                admissions_count=2, discharges_count=1, transfers_count=0, snapshots_count=2,
                waiting_queue_count=None, bed_turnaround_count=None,
            )
        owned = run("00000000-0000-0000-0000-000000000001", user.id)
        historical = run("00000000-0000-0000-0000-000000000002", None)
        guest = run("00000000-0000-0000-0000-000000000003", user.id, guest_id=999)
        deleted = run("00000000-0000-0000-0000-000000000004", user.id,
                      deleted_at=datetime(2026, 1, 3, tzinfo=timezone.utc))
        db.add_all([owned, historical, guest, deleted]); db.flush()
        cookies = {"admin": create_session(db, admin), "user": create_session(db, user)}
        user_id, run_id, guest_run_id = user.id, owned.run_id, guest.run_id
        db.commit()
        return cookies, user_id, run_id, guest_run_id


def test_admin_user_overview_returns_only_safe_metadata_and_visible_runs(overview_client):
    cookies, user_id, run_id, guest_run_id = seed(overview_client)
    overview_client.cookies.set("bedsynth_session", cookies["admin"])
    listing = overview_client.get("/api/v1/admin/overview/users")
    assert listing.status_code == 200
    account = next(row for row in listing.json()["items"] if row["id"] == user_id)
    assert account["email"] == "researcher@overview.test"
    assert account["completed_dataset_count"] == 1
    assert "password_hash" not in str(listing.json()) and "last_login_at" not in str(listing.json())

    response = overview_client.get(f"/api/v1/admin/overview/users/{user_id}")
    assert response.status_code == 200
    body = response.json()
    assert [item["run_id"] for item in body["runs"]] == [run_id]
    assert guest_run_id not in str(body)
    run = body["runs"][0]
    assert run["hospital_name"] == "Overview Hospital"
    assert run["scenario_name"] == "Normal Operations"
    assert run["departments"] == ["Cardiology"]
    assert run["target_admissions"] == 2 and run["seed"] == 1234
    assert run["record_counts"]["admissions"] == 0  # no patient-level rows were seeded
    forbidden = {"patient_id", "synthetic_patient_id", "password_hash", "token_hash", "sessions", "guest_session_id", "config"}
    assert forbidden.isdisjoint(body.keys())
    assert forbidden.isdisjoint(run.keys())
    user_routes = {path: operations for path, operations in app.openapi()["paths"].items()
                   if path.startswith("/api/v1/admin/overview/users")}
    assert user_routes
    assert all(not ({"post", "patch", "put", "delete"} & operations.keys())
               for operations in user_routes.values())


def test_admin_user_overview_is_admin_only(overview_client):
    _cookies, user_id, _run_id, _guest_run_id = seed(overview_client)
    assert overview_client.get("/api/v1/admin/overview/users").status_code == 401
    overview_client.cookies.set("bedsynth_session", _cookies["user"])
    assert overview_client.get("/api/v1/admin/overview/users").status_code == 403
    assert overview_client.get(f"/api/v1/admin/overview/users/{user_id}").status_code == 403


def test_missing_user_returns_not_found(overview_client):
    _cookies, *_ = seed(overview_client)
    overview_client.cookies.set("bedsynth_session", _cookies["admin"])
    assert overview_client.get("/api/v1/admin/overview/users/9999").status_code == 404
