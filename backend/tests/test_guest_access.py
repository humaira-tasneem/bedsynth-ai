from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.auth import create_session, current_user, utc_now
from app.database import Base, get_db
from app.guest_routes import guest_generation_limiter, guest_preview_limiter, guest_session_limiter
from app.main import app
from app.models import Bed, Department, GenerationRun, GuestSession, Hospital, User, Workspace
from app.security import InMemoryWindowLimiter


@pytest.fixture
def guest_client(tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'guest-test.db').as_posix()}", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
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
    app.dependency_overrides.pop(current_user, None)
    guest_session_limiter.reset(); guest_preview_limiter.reset(); guest_generation_limiter.reset()
    try:
        with TestClient(app) as client:
            client.test_sessions = sessions
            client.headers.update({"Origin": "http://localhost:3000"})
            yield client
    finally:
        app.dependency_overrides.clear()
        app.router.lifespan_context = old_lifespan
        guest_session_limiter.reset(); guest_preview_limiter.reset(); guest_generation_limiter.reset()
        engine.dispose()


def _hospital(client: TestClient, *, shared: bool = True) -> tuple[int, int]:
    with client.test_sessions() as db:
        workspace = Workspace(name=f"Guest workspace {uuid4()}", is_shared=shared)
        db.add(workspace); db.flush()
        hospital = Hospital(workspace_id=workspace.id, name="Fictional Shared Hospital", code=f"G-{uuid4().hex[:8]}")
        db.add(hospital); db.flush()
        department = Department(hospital_id=hospital.id, code="GEN", name="General", bed_capacity=2)
        db.add(department); db.flush()
        db.add_all([
            Bed(hospital_id=hospital.id, department_id=department.id, code="GEN-1", category="general", status="operational"),
            Bed(hospital_id=hospital.id, department_id=department.id, code="GEN-2", category="general", status="operational"),
        ])
        db.commit()
        return workspace.id, hospital.id


def _start_guest(client: TestClient) -> dict:
    response = client.post("/api/v1/guest/sessions")
    assert response.status_code == 201, response.text
    assert "httponly" in response.headers["set-cookie"].lower()
    return response.json()


def _config() -> dict:
    return {"start_date": "2025-01-01", "end_date": "2025-01-03", "target_admissions": 2,
            "target_occupancy_pct": 70, "seed": 2025}


def _generate_guest(client: TestClient, hospital_id: int) -> dict:
    config = _config()
    preview = client.post(f"/api/v1/guest/hospitals/{hospital_id}/generation-runs/preview", json=config)
    assert preview.status_code == 200, preview.text
    create = client.post(f"/api/v1/guest/hospitals/{hospital_id}/generation-runs", json={
        **config, "idempotency_key": str(uuid4()), "preview_token": preview.json()["preview_token"],
    })
    assert create.status_code == 200, create.text
    return create.json()


def test_guest_session_lists_only_shared_hospitals_and_can_generate_download(guest_client: TestClient) -> None:
    shared_workspace_id, shared_hospital_id = _hospital(guest_client)
    _hospital(guest_client, shared=False)
    session = _start_guest(guest_client)
    assert guest_client.get("/api/v1/guest/session").json()["expires_at"] == session["expires_at"]
    workspaces = guest_client.get("/api/v1/guest/workspaces").json()
    assert [row["id"] for row in workspaces] == [shared_workspace_id]
    hospitals = guest_client.get(f"/api/v1/guest/workspaces/{shared_workspace_id}/hospitals").json()
    assert [row["id"] for row in hospitals] == [shared_hospital_id]

    run = _generate_guest(guest_client, shared_hospital_id)
    with guest_client.test_sessions() as db:
        stored = db.get(GenerationRun, run["run_id"])
        assert stored.guest_session_id is not None and stored.owner_user_id is None
    detail = guest_client.get(f"/api/v1/guest/generation-runs/{run['run_id']}/dataset")
    assert detail.status_code == 200
    export = guest_client.get(f"/api/v1/guest/generation-runs/{run['run_id']}/dataset/export/admissions")
    assert export.status_code == 200 and "admission_type" in export.text
    manifest = guest_client.get(f"/api/v1/guest/generation-runs/{run['run_id']}/dataset/manifest")
    assert manifest.status_code == 200
    assert guest_client.post(f"/api/v1/guest/generation-runs/{run['run_id']}/validations").status_code == 201
    assert guest_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset").status_code == 401
    assert guest_client.get("/api/v1/admin/dashboard").status_code == 401
    assert guest_client.patch(f"/api/v1/workspaces/{shared_workspace_id}/hospitals/{shared_hospital_id}", json={"name": "changed"}).status_code == 401

    with guest_client.test_sessions() as db:
        admin = User(email="guest-isolation-admin@example.test", password_hash="test-hash", role="admin", is_active=True)
        db.add(admin); db.commit(); db.refresh(admin)
        admin_cookie = create_session(db, admin)
    guest_client.cookies.set("bedsynth_session", admin_cookie)
    assert guest_client.get("/api/v1/admin/datasets").json()["total"] == 0
    assert guest_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset").status_code == 404


def test_guest_datasets_are_isolated_between_sessions(guest_client: TestClient) -> None:
    _, hospital_id = _hospital(guest_client)
    _start_guest(guest_client)
    run = _generate_guest(guest_client, hospital_id)
    other = TestClient(app)
    other.headers.update({"Origin": "http://localhost:3000"})
    _start_guest(other)
    assert other.get(f"/api/v1/guest/generation-runs/{run['run_id']}/dataset").status_code == 404
    other.close()


def test_guest_input_limits_and_guest_creation_rate_limit(guest_client: TestClient) -> None:
    _, hospital_id = _hospital(guest_client)
    _start_guest(guest_client)
    too_many = _config() | {"target_admissions": 501}
    assert guest_client.post(f"/api/v1/guest/hospitals/{hospital_id}/generation-runs/preview", json=too_many).status_code == 422
    too_long = _config() | {"end_date": "2025-02-05"}
    assert guest_client.post(f"/api/v1/guest/hospitals/{hospital_id}/generation-runs/preview", json=too_long).status_code == 422
    scenario_expansion = _config() | {"target_admissions": 500, "scenario": "emergency_surge"}
    expanded = guest_client.post(f"/api/v1/guest/hospitals/{hospital_id}/generation-runs/preview", json=scenario_expansion)
    assert expanded.status_code == 422 and "project more than 500" in expanded.json()["detail"]

    guest_session_limiter.reset()
    for _ in range(5):
        assert guest_client.post("/api/v1/guest/sessions").status_code == 201
    limited = guest_client.post("/api/v1/guest/sessions")
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0


def test_expired_guest_session_is_denied_and_cleanup_preserves_registered_runs(guest_client: TestClient) -> None:
    workspace_id, hospital_id = _hospital(guest_client)
    _start_guest(guest_client)
    guest_run = _generate_guest(guest_client, hospital_id)
    with guest_client.test_sessions() as db:
        guest = db.scalar(select(GuestSession))
        guest.expires_at = utc_now() - timedelta(seconds=1)
        user = User(email="registered@example.test", password_hash="test-hash", role="user", is_active=True)
        db.add(user); db.flush()
        registered_run = GenerationRun(run_id=str(uuid4()), workspace_id=workspace_id, hospital_id=hospital_id,
            owner_user_id=user.id, idempotency_key=str(uuid4()), config={}, seed=9, status="completed")
        db.add(registered_run); db.commit()
        registered_id = registered_run.run_id
        user_id = user.id

    assert guest_client.get(f"/api/v1/guest/generation-runs/{guest_run['run_id']}/dataset").status_code == 401
    with guest_client.test_sessions() as db:
        from app.guest_routes import cleanup_expired_guest_sessions
        assert cleanup_expired_guest_sessions(db) == 1
        assert db.get(GenerationRun, guest_run["run_id"]) is None
        assert db.get(GenerationRun, registered_id) is not None
        assert db.get(User, user_id) is not None


def test_guest_cannot_confirm_generation_against_private_hospital(guest_client: TestClient) -> None:
    _, hospital_id = _hospital(guest_client, shared=False)
    _start_guest(guest_client)
    response = guest_client.post(f"/api/v1/guest/hospitals/{hospital_id}/generation-runs/preview", json=_config())
    assert response.status_code == 404


def test_guest_generation_rate_limit_prevents_confirmation_before_writing(guest_client: TestClient) -> None:
    _, hospital_id = _hospital(guest_client)
    _start_guest(guest_client)
    with guest_client.test_sessions() as db:
        guest = db.scalar(select(GuestSession))
        session_key = f"{guest.id}:testclient"
    for _ in range(5):
        guest_generation_limiter.record(session_key)
    request = _config() | {"idempotency_key": str(uuid4()), "preview_token": "0" * 64}
    response = guest_client.post(f"/api/v1/guest/hospitals/{hospital_id}/generation-runs", json=request)
    assert response.status_code == 429
    with guest_client.test_sessions() as db:
        assert db.scalar(select(GenerationRun.idempotency_key).where(GenerationRun.guest_session_id == guest.id)) is None


def test_guest_preview_is_read_only_and_confirmation_keeps_idempotency(guest_client: TestClient) -> None:
    _, hospital_id = _hospital(guest_client)
    _start_guest(guest_client)
    config = _config()
    preview = guest_client.post(f"/api/v1/guest/hospitals/{hospital_id}/generation-runs/preview", json=config)
    assert preview.status_code == 200
    with guest_client.test_sessions() as db:
        assert db.scalar(select(GenerationRun.run_id)) is None
    payload = config | {"idempotency_key": str(uuid4()), "preview_token": preview.json()["preview_token"]}
    first = guest_client.post(f"/api/v1/guest/hospitals/{hospital_id}/generation-runs", json=payload)
    second = guest_client.post(f"/api/v1/guest/hospitals/{hospital_id}/generation-runs", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["run_id"] == second.json()["run_id"]
    with guest_client.test_sessions() as db:
        assert len(list(db.scalars(select(GenerationRun.run_id)).all())) == 1


def test_guest_dataset_route_cannot_read_registered_or_legacy_runs(guest_client: TestClient) -> None:
    workspace_id, hospital_id = _hospital(guest_client)
    _start_guest(guest_client)
    with guest_client.test_sessions() as db:
        user = User(email="existing-run@example.test", password_hash="test-hash", role="user", is_active=True)
        db.add(user); db.flush()
        run = GenerationRun(run_id=str(uuid4()), workspace_id=workspace_id, hospital_id=hospital_id,
            owner_user_id=user.id, idempotency_key=str(uuid4()), config={}, seed=1, status="completed")
        db.add(run); db.commit()
        run_id = run.run_id
    assert guest_client.get(f"/api/v1/guest/generation-runs/{run_id}/dataset").status_code == 404
