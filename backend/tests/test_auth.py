"""Authentication, authorization, ownership, and CSRF regression tests."""

from collections.abc import Generator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth import current_user, hash_password
from app.database import Base, get_db
from app.main import app
from app.auth_routes import _cookie_options
from app.models import AccountActivityEvent, GenerationRun, Hospital, User, UserSession, Workspace
from app.security import InMemoryWindowLimiter


@pytest.fixture
def auth_client(tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'auth-test.db').as_posix()}", connect_args={"check_same_thread": False})
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
    try:
        with TestClient(app) as client:
            client.test_sessions = sessions
            client.headers.update({"Origin": "http://localhost:3000"})
            yield client
    finally:
        app.dependency_overrides.clear()
        app.router.lifespan_context = old_lifespan
        engine.dispose()


def make_admin(client: TestClient, email="admin@example.test") -> dict:
    with client.test_sessions() as db:
        user = User(email=email, password_hash=hash_password("correct-horse-battery-staple"), role="admin", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"id": user.id, "email": user.email, "role": user.role}


def login(client: TestClient, email="admin@example.test", password="correct-horse-battery-staple"):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers={"Origin": "http://localhost:3000"})


def test_auth_required_registration_and_http_only_cookie(auth_client: TestClient) -> None:
    assert auth_client.get("/api/v1/workspaces").status_code == 401
    response = auth_client.post("/api/v1/auth/register", json={"email": " User@Example.test ", "password": "long-password-123"}, headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 201
    assert response.json()["role"] == "user"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert "password_hash" not in response.json()
    assert auth_client.get("/api/v1/auth/me").json()["email"] == "user@example.test"


def test_account_settings_password_change_and_audit_tracking(auth_client: TestClient) -> None:
    registration = auth_client.post("/api/v1/auth/register", json={
        "email": "activity-user@example.test", "password": "correct-password-123",
    })
    assert registration.status_code == 201
    user_id = registration.json()["id"]
    assert registration.json()["last_login_at"] is None
    settings = auth_client.get("/api/v1/auth/settings")
    assert settings.status_code == 200
    assert settings.json()["account"]["email"] == "activity-user@example.test"
    assert settings.json()["session_expires_at"]
    assert "password_hash" not in settings.text and "token" not in settings.text.lower()

    assert auth_client.post("/api/v1/auth/login", json={
        "email": "activity-user@example.test", "password": "wrong-password",
    }).status_code == 401
    with auth_client.test_sessions() as db:
        events = list(db.scalars(select(AccountActivityEvent).where(AccountActivityEvent.target_user_id == user_id)))
        assert [event.event_type for event in events] == ["account_registered"]

    auth_client.post("/api/v1/auth/logout")
    login_response = auth_client.post("/api/v1/auth/login", json={
        "email": "activity-user@example.test", "password": "correct-password-123",
    })
    assert login_response.status_code == 200 and login_response.json()["last_login_at"] is not None
    assert auth_client.get("/api/v1/admin/account-activity").status_code == 403
    changed = auth_client.post("/api/v1/auth/change-password", json={
        "current_password": "correct-password-123", "new_password": "new-correct-password-456",
    })
    assert changed.status_code == 204
    assert auth_client.post("/api/v1/auth/change-password", json={
        "current_password": "wrong-password", "new_password": "another-correct-password-789",
    }).status_code == 400
    auth_client.post("/api/v1/auth/logout")

    make_admin(auth_client)
    assert login(auth_client).status_code == 200
    assert auth_client.patch(f"/api/v1/admin/users/{user_id}", json={"role": "admin"}).status_code == 200
    assert auth_client.patch(f"/api/v1/admin/users/{user_id}", json={"is_active": False}).status_code == 200
    assert auth_client.patch(f"/api/v1/admin/users/{user_id}", json={"is_active": True}).status_code == 200
    global_events = auth_client.get(f"/api/v1/admin/account-activity?target_id={user_id}&page=1&page_size=100")
    assert global_events.status_code == 200
    items = global_events.json()["items"]
    event_types = {item["event_type"] for item in items}
    assert {"account_registered", "login_succeeded", "logout", "password_changed", "role_changed", "account_deactivated", "account_activated"} <= event_types
    assert all("correct-password-123" not in str(item) and "new-correct-password-456" not in str(item)
               and "scrypt$" not in str(item) for item in items)
    timeline = auth_client.get(f"/api/v1/admin/users/{user_id}/activity?event_type=login_succeeded")
    assert timeline.status_code == 200 and timeline.json()["total"] == 1
    assert auth_client.get("/api/v1/admin/account-activity?page=0").status_code == 422


def test_production_cookie_cannot_be_configured_without_secure_flag(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("SESSION_COOKIE_SAMESITE", "lax")
    assert _cookie_options()["secure"] is True
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SESSION_COOKIE_SAMESITE", "none")
    assert _cookie_options()["secure"] is True


def test_duplicate_registration_casefolds_email_and_password_is_not_returned(auth_client: TestClient) -> None:
    body = {"email": "user@example.test", "password": "long-password-123"}
    assert auth_client.post("/api/v1/auth/register", json=body).status_code == 201
    duplicate = auth_client.post("/api/v1/auth/register", json={**body, "email": "USER@EXAMPLE.TEST"})
    assert duplicate.status_code == 409
    with auth_client.test_sessions() as db:
        user = db.scalar(select(User).where(User.email == "user@example.test"))
        assert user.password_hash != body["password"]


def test_registration_cannot_assign_an_administrator_role(auth_client: TestClient) -> None:
    response = auth_client.post("/api/v1/auth/register", json={
        "email": "untrusted-role@example.test", "password": "long-password-456", "role": "admin",
    })
    assert response.status_code == 201
    assert response.json()["role"] == "user"


def test_login_rate_limit_returns_retry_after_without_account_disclosure(auth_client: TestClient) -> None:
    email = "rate-limited-unique@example.test"
    for _ in range(8):
        response = auth_client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Email or password is incorrect."
    limited = auth_client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0


def test_registration_window_limiter_rejects_excess_and_can_reset() -> None:
    limiter = InMemoryWindowLimiter()
    key = "test-client"
    assert limiter.retry_after(key, limit=2, window_seconds=60) is None
    limiter.record(key); limiter.record(key)
    assert (limiter.retry_after(key, limit=2, window_seconds=60) or 0) > 0
    limiter.reset()
    assert limiter.retry_after(key, limit=2, window_seconds=60) is None


def test_security_headers_are_added_and_api_responses_are_not_cached(auth_client: TestClient) -> None:
    response = auth_client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    private_api = auth_client.get("/api/v1/auth/me")
    assert private_api.headers["cache-control"] == "no-store"


def test_generic_login_failure_and_logout_revokes_session(auth_client: TestClient) -> None:
    make_admin(auth_client)
    wrong = login(auth_client, password="wrong-password")
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "Email or password is incorrect."
    assert login(auth_client).status_code == 200
    assert auth_client.get("/api/v1/auth/me").status_code == 200
    assert auth_client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:3000"}).status_code == 204
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_user_is_restricted_to_shared_workspaces_and_admin_writes(auth_client: TestClient) -> None:
    make_admin(auth_client)
    admin = login(auth_client)
    workspace = auth_client.post("/api/v1/workspaces", json={"name": "Private"}, headers={"Origin": "http://localhost:3000"}).json()
    user_response = auth_client.post("/api/v1/auth/register", json={"email": "member@example.test", "password": "long-password-456"}, headers={"Origin": "http://localhost:3000"})
    assert user_response.status_code == 201
    assert auth_client.get(f"/api/v1/workspaces/{workspace['id']}/hospitals").status_code == 404
    assert auth_client.post(f"/api/v1/workspaces/{workspace['id']}/hospitals", json={"name": "X", "code": "X"}).status_code == 403
    auth_client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:3000"})
    auth_client.cookies.clear()
    auth_client.cookies.update({"bedsynth_session": admin.cookies.get("bedsynth_session")})
    assert auth_client.patch(f"/api/v1/admin/workspaces/{workspace['id']}/sharing", json={"is_shared": True}).status_code == 200
    auth_client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:3000"})
    auth_client.post("/api/v1/auth/login", json={"email": "member@example.test", "password": "long-password-456"}, headers={"Origin": "http://localhost:3000"})
    assert [item["id"] for item in auth_client.get("/api/v1/workspaces").json()] == [workspace["id"]]


def test_non_admin_cannot_call_admin_routes_and_last_admin_is_protected(auth_client: TestClient) -> None:
    make_admin(auth_client)
    assert login(auth_client).status_code == 200
    assert auth_client.get("/api/v1/admin/users").status_code == 200
    assert auth_client.patch("/api/v1/admin/users/1", json={"role": "user"}).status_code == 409
    assert auth_client.patch("/api/v1/admin/users/1", json={"is_active": False}).status_code == 409
    auth_client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:3000"})
    ordinary = auth_client.post("/api/v1/auth/register", json={"email": "ordinary@example.test", "password": "long-password-789"}, headers={"Origin": "http://localhost:3000"})
    assert auth_client.get("/api/v1/admin/users").status_code == 403
    assert auth_client.patch(f"/api/v1/admin/users/{ordinary.json()['id']}", json={"role": "admin"}).status_code == 403


def test_deactivation_invalidates_existing_session(auth_client: TestClient) -> None:
    make_admin(auth_client)
    target_response = auth_client.post("/api/v1/auth/register", json={"email": "target@example.test", "password": "long-password-000"}, headers={"Origin": "http://localhost:3000"})
    target_cookie = target_response.cookies.get("bedsynth_session")
    target_id = auth_client.get("/api/v1/auth/me").json()["id"]
    auth_client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:3000"})
    login(auth_client)
    updated = auth_client.patch(f"/api/v1/admin/users/{target_id}", json={"is_active": False})
    assert updated.status_code == 200
    auth_client.cookies.clear()
    auth_client.cookies.update({"bedsynth_session": target_cookie})
    assert auth_client.get("/api/v1/auth/me").status_code == 401
    with auth_client.test_sessions() as db:
        assert db.scalar(select(UserSession).where(UserSession.user_id == target_id)) is None


def test_foreign_and_historical_runs_are_not_exposed_to_user(auth_client: TestClient) -> None:
    make_admin(auth_client)
    with auth_client.test_sessions() as db:
        owner = User(email="owner@example.test", password_hash=hash_password("long-password-abc"), role="user", is_active=True)
        other = User(email="other@example.test", password_hash=hash_password("long-password-def"), role="user", is_active=True)
        workspace = Workspace(name="Shared", is_shared=True)
        db.add_all([owner, other, workspace]); db.flush()
        hospital = Hospital(workspace_id=workspace.id, name="Shared Simulation Hospital", code="SHARED")
        db.add(hospital); db.flush()
        run = GenerationRun(run_id="owned-run", workspace_id=workspace.id, hospital_id=hospital.id, owner_user_id=owner.id, idempotency_key="00000000-0000-0000-0000-000000000000", config={"request": {}}, seed=1, status="completed")
        historical = GenerationRun(run_id="legacy-run", workspace_id=workspace.id, hospital_id=hospital.id, owner_user_id=None, idempotency_key="00000000-0000-0000-0000-000000000001", config={"request": {}}, seed=1, status="completed")
        db.add_all([run, historical]);
        db.commit()
        other_email = other.email
    auth_client.post("/api/v1/auth/login", json={"email": other_email, "password": "long-password-def"}, headers={"Origin": "http://localhost:3000"})
    assert auth_client.get("/api/v1/generation-runs/owned-run/dataset").status_code == 404
    assert auth_client.get("/api/v1/generation-runs/legacy-run/dataset").status_code == 404
    assert auth_client.get("/api/v1/generation-runs/owned-run/dataset/export/patients").status_code == 404
    assert auth_client.get("/api/v1/generation-runs/legacy-run/dataset/manifest").status_code == 404
    assert auth_client.get("/api/v1/analytics/hospitals/1/runs").json()["items"] == []


def test_cross_origin_cookie_mutation_is_rejected(auth_client: TestClient) -> None:
    make_admin(auth_client); login(auth_client)
    response = auth_client.post("/api/v1/assistant/chat", json={"workspace_id": 1, "message": "hi"}, headers={"Origin": "https://attacker.invalid"})
    assert response.status_code == 403


def test_new_generation_is_owned_and_visible_only_to_its_creator(auth_client: TestClient) -> None:
    from test_synthetic_generation import generation_config, make_hospital, preview_and_generate

    make_admin(auth_client)
    assert login(auth_client).status_code == 200
    workspace_id, hospital_id, departments = make_hospital(auth_client, department_count=1, beds_per_department=2)
    with auth_client.test_sessions() as db:
        workspace = db.get(Workspace, workspace_id)
        workspace.is_shared = True
        db.commit()
    response = auth_client.post("/api/v1/auth/register", json={"email": "creator@example.test", "password": "long-password-own"}, headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 201
    creator_id = response.json()["id"]
    run = preview_and_generate(auth_client, hospital_id, generation_config(departments, admissions=1))
    with auth_client.test_sessions() as db:
        stored = db.get(GenerationRun, run["run_id"])
        assert stored.owner_user_id == creator_id
    listing = auth_client.get(f"/api/v1/workspaces/{workspace_id}/datasets")
    assert listing.status_code == 200 and [item["run_id"] for item in listing.json()["items"]] == [run["run_id"]]
    with auth_client.test_sessions() as db:
        generated_event = db.scalar(select(AccountActivityEvent).where(
            AccountActivityEvent.run_id == run["run_id"], AccountActivityEvent.event_type == "dataset_generated"))
        assert generated_event is not None and generated_event.actor_user_id == creator_id
    assert auth_client.delete(f"/api/v1/generation-runs/{run['run_id']}/dataset").status_code == 204
    with auth_client.test_sessions() as db:
        deleted_event = db.scalar(select(AccountActivityEvent).where(
            AccountActivityEvent.run_id == run["run_id"], AccountActivityEvent.event_type == "dataset_soft_deleted"))
        assert deleted_event is not None and deleted_event.actor_user_id == creator_id
    auth_client.post("/api/v1/auth/register", json={"email": "another@example.test", "password": "long-password-two"}, headers={"Origin": "http://localhost:3000"})
    assert auth_client.get(f"/api/v1/generation-runs/{run['run_id']}/dataset").status_code == 404
