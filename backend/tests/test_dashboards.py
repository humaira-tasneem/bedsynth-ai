"""Role-scoped dashboard and admin dataset endpoint tests."""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import create_session, hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Admission, Bed, Department, GenerationRun, Hospital, OccupancySnapshot, SyntheticPatient, User, Workspace


@pytest.fixture
def dashboard_client(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'dashboard-test.db').as_posix()}", connect_args={"check_same_thread": False})
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


def _seed(client):
    with client.test_sessions() as db:
        admin = User(email="admin@bedsynth.test", password_hash=hash_password("test-password-admin"), role="admin", is_active=True)
        owner = User(email="owner@bedsynth.test", password_hash=hash_password("test-password-owner"), role="user", is_active=True)
        other = User(email="other@bedsynth.test", password_hash=hash_password("test-password-other"), role="user", is_active=True)
        inactive = User(email="inactive@bedsynth.test", password_hash=hash_password("test-password-inactive"), role="user", is_active=False)
        workspace = Workspace(name="Shared test workspace", is_shared=True)
        private_workspace = Workspace(name="Private test workspace", is_shared=False)
        db.add_all([admin, owner, other, inactive, workspace, private_workspace]); db.flush()
        hospital = Hospital(workspace_id=workspace.id, name="Shared Test Hospital", code="STH")
        private_hospital = Hospital(workspace_id=private_workspace.id, name="Private Test Hospital", code="PTH")
        db.add_all([hospital, private_hospital]); db.flush()
        department = Department(hospital_id=hospital.id, code="GEN", name="General", bed_capacity=2)
        db.add(department); db.flush()
        bed = Bed(hospital_id=hospital.id, department_id=department.id, code="GEN-001", category="general", status="operational")
        db.add(bed); db.flush()
        def run(run_id, owner_id, workspace_id, key_suffix, deleted_at=None, hospital_id=None):
            return GenerationRun(run_id=run_id, workspace_id=workspace_id, hospital_id=hospital_id or hospital.id,
                                 owner_user_id=owner_id, deleted_at=deleted_at,
                                 idempotency_key=f"00000000-0000-0000-0000-{key_suffix:012d}",
                                 config={"generator_version": "test", "request": {"scenario": "normal_operations"}},
                                 seed=42, status="completed", patients_count=1, admissions_count=1)
        from datetime import datetime, timezone
        owned = run("00000000-0000-0000-0000-000000000001", owner.id, workspace.id, 1)
        foreign = run("00000000-0000-0000-0000-000000000002", other.id, workspace.id, 2)
        historical = run("00000000-0000-0000-0000-000000000003", None, workspace.id, 3)
        deleted = run("00000000-0000-0000-0000-000000000004", owner.id, workspace.id, 4, datetime.now(timezone.utc))
        outside = run("00000000-0000-0000-0000-000000000005", owner.id, private_workspace.id, 5, hospital_id=private_hospital.id)
        db.add_all([owned, foreign, historical, deleted, outside]); db.flush()
        patient = SyntheticPatient(run_id=owned.run_id, workspace_id=workspace.id, hospital_id=hospital.id,
                                   synthetic_patient_id="SYN-1", age_band="18-34", age_years=25, gender="other")
        db.add(patient); db.flush()
        admission = Admission(run_id=owned.run_id, workspace_id=workspace.id, hospital_id=hospital.id,
                              patient_id=patient.id, department_id=department.id, initial_bed_id=bed.id,
                              admitted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc), status="discharged")
        db.add(admission); db.flush()
        db.add(OccupancySnapshot(run_id=owned.run_id, workspace_id=workspace.id, hospital_id=hospital.id,
                                 department_id=department.id, snapshot_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                                 operational_beds=1, occupied_beds=1, available_beds=0, occupancy_pct=100.0))
        cookies = {role: create_session(db, user) for role, user in (("admin", admin), ("owner", owner), ("other", other))}
        db.commit()
        return cookies


def test_user_dashboard_is_owned_and_excludes_deleted_and_historical(dashboard_client):
    cookies = _seed(dashboard_client)
    dashboard_client.cookies.set("bedsynth_session", cookies["owner"])
    response = dashboard_client.get("/api/v1/dashboard/user")
    assert response.status_code == 200
    body = response.json()
    # Ownership, rather than workspace sharing, controls dataset visibility.
    assert body["total_datasets"] == 2
    assert body["total_generated_records"] == 3
    assert body["latest_occupancy_pct"] == 100.0
    assert {run["run_id"] for run in body["recent_runs"]} == {
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000005",
    }
    assert dashboard_client.get("/api/v1/admin/dashboard").status_code == 403


def test_admin_dashboard_and_dataset_listing_are_owner_scoped(dashboard_client):
    cookies = _seed(dashboard_client)
    dashboard_client.cookies.set("bedsynth_session", cookies["admin"])
    dashboard = dashboard_client.get("/api/v1/admin/dashboard")
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["total_registered_users"] == 4
    assert body["active_users"] == 3
    assert body["shared_hospitals"] == 1
    assert body["departments"] == 1 and body["beds"] == 1
    assert body["generation_runs"] == 0
    assert body["generated_records"] == 0
    assert body["recent_activity"] == []
    listing = dashboard_client.get("/api/v1/admin/datasets?page_size=100")
    assert listing.status_code == 200
    assert listing.json()["items"] == []
    historical = dashboard_client.get("/api/v1/admin/datasets?ownership=historical")
    assert historical.json()["items"] == []
    with_deleted = dashboard_client.get("/api/v1/admin/datasets?include_deleted=true")
    assert with_deleted.json()["total"] == 0


def test_admin_user_management_stats_filters_pagination_activity_and_detail(dashboard_client):
    cookies = _seed(dashboard_client)
    dashboard_client.cookies.set("bedsynth_session", cookies["admin"])

    stats = dashboard_client.get("/api/v1/admin/users/stats")
    assert stats.status_code == 200
    assert stats.json() == {
        "total_accounts": 4, "active_accounts": 3, "deactivated_accounts": 1,
        "administrators": 1, "standard_users": 3,
        "registrations_7d": 4, "registrations_30d": 4,
    }

    activity = dashboard_client.get("/api/v1/admin/users/activity?days=7")
    assert activity.status_code == 200
    assert len(activity.json()["items"]) == 7
    assert sum(point["registrations"] for point in activity.json()["items"]) == 4

    filtered = dashboard_client.get("/api/v1/admin/users?role=user&status=active&q=owner&page=1&page_size=1")
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1 and body["pages"] == 1 and body["page"] == 1
    assert body["items"][0]["email"] == "owner@bedsynth.test"
    assert body["items"][0]["dataset_count"] == 2
    assert "password_hash" not in body["items"][0]

    first_page = dashboard_client.get("/api/v1/admin/users?page=1&page_size=2&sort=oldest").json()
    second_page = dashboard_client.get("/api/v1/admin/users?page=2&page_size=2&sort=oldest").json()
    assert first_page["total"] == 4 and first_page["pages"] == 2
    assert first_page["items"][0]["created_at"] <= first_page["items"][1]["created_at"]
    assert len(second_page["items"]) == 2
    assert {item["id"] for item in first_page["items"]}.isdisjoint(item["id"] for item in second_page["items"])

    detail = dashboard_client.get(f"/api/v1/admin/users/{body['items'][0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["dataset_count"] == 2
    assert "last_login" not in detail.json()
    assert dashboard_client.get("/api/v1/admin/users/99999").status_code == 404
    assert dashboard_client.get("/api/v1/admin/users?role=owner").status_code == 422


def test_admin_user_management_is_admin_only(dashboard_client):
    cookies = _seed(dashboard_client)
    assert dashboard_client.get("/api/v1/admin/users/stats").status_code == 401
    dashboard_client.cookies.set("bedsynth_session", cookies["owner"])
    assert dashboard_client.get("/api/v1/admin/users/activity").status_code == 403


def test_custom_registration_date_ranges_aggregate_and_filter_accounts(dashboard_client):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select

    cookies = _seed(dashboard_client)
    with dashboard_client.test_sessions() as db:
        users = {user.email: user for user in db.scalars(select(User)).all()}
        today = datetime.now(timezone.utc).date()
        users["admin@bedsynth.test"].created_at = datetime.combine(today, datetime.min.time(), timezone.utc)
        users["owner@bedsynth.test"].created_at = datetime.combine(today - timedelta(days=12), datetime.min.time(), timezone.utc)
        users["other@bedsynth.test"].created_at = datetime.combine(today - timedelta(days=60), datetime.min.time(), timezone.utc)
        users["inactive@bedsynth.test"].created_at = datetime.combine(today - timedelta(days=180), datetime.min.time(), timezone.utc)
        db.commit()
    dashboard_client.cookies.set("bedsynth_session", cookies["admin"])

    same_day = today.isoformat()
    stats = dashboard_client.get(f"/api/v1/admin/users/registration-stats?from_date={same_day}&to_date={same_day}")
    assert stats.status_code == 200
    assert stats.json()["registered_accounts"] == 1
    assert stats.json()["active_registered_accounts"] == 1
    assert stats.json()["new_administrators"] == 1
    assert stats.json()["new_standard_users"] == 0

    series = dashboard_client.get(f"/api/v1/admin/users/registration-activity?from_date={today - timedelta(days=14)}&to_date={same_day}")
    assert series.status_code == 200 and series.json()["granularity"] == "day"
    assert len(series.json()["items"]) == 15
    assert sum(item["registrations"] for item in series.json()["items"]) == 2
    long_series = dashboard_client.get(f"/api/v1/admin/users/registration-activity?from_date={today - timedelta(days=120)}&to_date={same_day}")
    assert long_series.status_code == 200 and long_series.json()["granularity"] == "week"
    all_time = dashboard_client.get("/api/v1/admin/users/registration-activity")
    assert all_time.status_code == 200 and all_time.json()["granularity"] == "month"

    dated_users = dashboard_client.get(f"/api/v1/admin/users?from_date={same_day}&to_date={same_day}").json()
    assert [item["email"] for item in dated_users["items"]] == ["admin@bedsynth.test"]
    empty_day = (today - timedelta(days=30)).isoformat()
    assert dashboard_client.get(f"/api/v1/admin/users/registration-stats?from_date={empty_day}&to_date={empty_day}").json()["registered_accounts"] == 0
    assert dashboard_client.get(f"/api/v1/admin/users/registration-stats?from_date={same_day}&to_date={today - timedelta(days=1)}").status_code == 422
    assert dashboard_client.get("/api/v1/admin/users/registration-activity?from_date=not-a-date").status_code == 422


def test_dashboard_routes_require_authentication(dashboard_client):
    assert dashboard_client.get("/api/v1/dashboard/user").status_code == 401
    assert dashboard_client.get("/api/v1/admin/dashboard").status_code == 401
