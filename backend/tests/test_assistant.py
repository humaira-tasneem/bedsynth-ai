"""Keyless assistant tests using an isolated database and mocked model output."""

from collections.abc import Generator
from contextlib import asynccontextmanager
import os
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.auth import current_user
from app.database import Base
from app.environment import BACKEND_ENV_FILE, load_backend_environment
from app.main import app
from app.models import Department, GenerationRun
from app.routes import get_db
from app.schemas import GeminiGenerationProposal
from app.services import assistant as assistant_service
from test_synthetic_generation import make_hospital


@pytest.fixture
def assistant_client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'assistant-test.db').as_posix()}", connect_args={"check_same_thread": False})
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

    previous_lifespan = app.router.lifespan_context
    app.router.lifespan_context = isolated_lifespan
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=None, role="admin", is_active=True)
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with TestClient(app) as client:
        client.test_sessions = sessions
        yield client
    app.dependency_overrides.clear()
    app.router.lifespan_context = previous_lifespan
    engine.dispose()


def ready_proposal(departments, **updates):
    values = {
        "assistant_message": "I prepared the requested configuration for review.",
        "hospital_name": "Fictional Generation Hospital",
        "start_date": "2027-01-01",
        "end_date": "2027-01-03",
        "target_admissions": 4,
        "target_occupancy_pct": 70,
        "seed": None,
        "department_names": [row["name"] for row in departments],
    }
    values.update(updates)
    return GeminiGenerationProposal(**values)


def patch_proposal(monkeypatch, proposal):
    captured = {}

    def interpret(message, history, hospitals, departments):
        captured.update(message=message, history=history, hospitals=hospitals, departments=departments)
        return proposal

    monkeypatch.setattr(assistant_service, "interpret_with_gemini", interpret)
    return captured


def test_backend_env_loader_uses_backend_relative_path_and_loads_from_other_cwd(tmp_path, monkeypatch):
    expected_path = Path(__file__).resolve().parents[1] / ".env"
    assert BACKEND_ENV_FILE == expected_path
    assert BACKEND_ENV_FILE.is_absolute()

    test_env_file = tmp_path / "backend" / ".env"
    test_env_file.parent.mkdir()
    test_env_file.write_text("GEMINI_API_KEY=unit-test-env-value\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    load_backend_environment(test_env_file)

    assert assistant_service.gemini_key_is_configured() is True
    assert os.environ["GEMINI_API_KEY"] == "unit-test-env-value"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_gemini_key_detection_rejects_missing_or_blank_values(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("GEMINI_API_KEY", value)
    assert assistant_service.gemini_key_is_configured() is False


def test_gemini_key_detection_accepts_nonempty_dummy_value(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    assert assistant_service.gemini_key_is_configured() is True


def test_assistant_status_reports_key_presence_without_claiming_provider_health(assistant_client, monkeypatch):
    configured = assistant_client.get("/api/v1/assistant/status")
    assert configured.status_code == 200
    assert configured.json() == {"gemini_key_configured": True, "groq_key_configured": False}

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    missing = assistant_client.get("/api/v1/assistant/status")
    assert missing.status_code == 200
    assert missing.json() == {"gemini_key_configured": False, "groq_key_configured": False}


def test_assistant_status_reports_groq_key_presence_only(assistant_client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-groq-key")
    response = assistant_client.get("/api/v1/assistant/status")
    assert response.status_code == 200
    assert response.json() == {"gemini_key_configured": True, "groq_key_configured": True}


def test_chat_resolves_real_hospital_and_departments_and_assigns_seed(assistant_client, monkeypatch):
    workspace_id, hospital_id, departments = make_hospital(assistant_client, beds_per_department=2)
    captured = patch_proposal(monkeypatch, ready_proposal(departments))
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": "Generate 4 admissions for Fictional Generation Hospital from January 1 to 3, 2027 at 70 percent.",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["assistant_source"] == "gemini"
    assert body["provider_category"] is None
    assert body["configuration"]["hospital_id"] == hospital_id
    assert body["configuration"]["department_ids"] == [row["id"] for row in departments]
    assert 0 <= body["configuration"]["seed"] <= 2_147_483_647
    assert body["seed_assigned_by_application"] is True
    assert "assigned seed" in body["assistant_message"]
    assert "id" not in captured["hospitals"][0]
    assert "id" not in captured["departments"][0]
    config = body["configuration"]
    preview = assistant_client.post(f"/api/v1/hospitals/{hospital_id}/generation-runs/preview", json={
        key: config[key] for key in ("start_date", "end_date", "target_admissions", "target_occupancy_pct", "seed", "department_ids")
    })
    assert preview.status_code == 200, preview.text
    with assistant_client.test_sessions() as db:
        assert db.scalar(select(func.count(GenerationRun.run_id))) == 0


def test_chat_asks_for_missing_fields_and_never_creates_a_run(assistant_client, monkeypatch):
    workspace_id, _, departments = make_hospital(assistant_client)
    patch_proposal(monkeypatch, GeminiGenerationProposal(
        assistant_message="I need a few more details.", hospital_name="Fictional Generation Hospital",
        start_date=None, end_date=None, target_admissions=None, target_occupancy_pct=None,
        seed=None, department_names=None,
    ))
    response = assistant_client.post("/api/v1/assistant/chat", json={"workspace_id": workspace_id, "message": "Generate a dataset for Fictional Generation Hospital."})
    assert response.status_code == 200
    assert response.json()["status"] == "needs_clarification"
    assert len(response.json()["questions"]) == 4
    with assistant_client.test_sessions() as db:
        assert db.scalar(select(func.count(GenerationRun.run_id))) == 0


def test_chat_uses_transparent_local_fallback_when_gemini_times_out(assistant_client, monkeypatch):
    workspace_id, hospital_id, departments = make_hospital(assistant_client, beds_per_department=2)

    def provider_timeout(*_args, **_kwargs):
        raise HTTPException(status_code=504, detail={"category": "timeout", "message": "Gemini timed out."})

    monkeypatch.setattr(assistant_service, "interpret_with_gemini", provider_timeout)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": "Include all departments.",
        "history": [
            {"role": "user", "content": (
                "Generate 100 synthetic admissions for Fictional Generation Hospital from "
                "October 1 to October 30, 2026, with a target occupancy of 70%."
            )},
            {"role": "assistant", "content": "Please specify the departments."},
        ],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["assistant_source"] == "local"
    assert body["provider_category"] == "timeout"
    assert body["configuration"]["hospital_id"] == hospital_id
    assert body["configuration"]["start_date"] == "2026-10-01"
    assert body["configuration"]["end_date"] == "2026-10-30"
    assert body["configuration"]["target_admissions"] == 100
    assert body["configuration"]["target_occupancy_pct"] == 70
    assert body["configuration"]["department_ids"] == [row["id"] for row in departments]
    assert "temporarily unavailable" in body["assistant_message"].casefold()
    assert body["seed_assigned_by_application"] is True
    with assistant_client.test_sessions() as db:
        assert db.scalar(select(func.count(GenerationRun.run_id))) == 0


def test_local_fallback_asks_for_missing_values_instead_of_inventing(assistant_client, monkeypatch):
    workspace_id, _, _ = make_hospital(assistant_client)

    def provider_unavailable(*_args, **_kwargs):
        raise HTTPException(status_code=503, detail={"category": "provider_unavailable", "message": "Gemini is unavailable."})

    monkeypatch.setattr(assistant_service, "interpret_with_gemini", provider_unavailable)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": "Help configure a dataset for Fictional Generation Hospital.",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert body["assistant_source"] == "local"
    assert body["provider_category"] == "provider_unavailable"
    assert body["configuration"] is None
    assert len(body["questions"]) == 4
    assert "temporarily unavailable" in body["assistant_message"].casefold()


@pytest.mark.parametrize("category", [
    "quota", "authentication", "model_not_found", "provider_unavailable",
    "network_error", "timeout", "malformed_response", "provider_error",
])
def test_all_gemini_failure_categories_use_explicit_local_parser_without_creating_records(
    assistant_client, monkeypatch, category,
):
    workspace_id, hospital_id, departments = make_hospital(assistant_client, beds_per_department=2)
    calls = {"provider": 0}

    def provider_failure(*_args, **_kwargs):
        calls["provider"] += 1
        raise HTTPException(status_code=502, detail={
            "category": category,
            "message": "Safe provider message.",
            "retry_after_seconds": 30 if category == "quota" else None,
        })

    monkeypatch.setattr(assistant_service, "interpret_with_gemini", provider_failure)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": (
            "Generate 4 admissions for Fictional Generation Hospital from January 1 to "
            "January 3, 2027 at 70% occupancy. Include all departments."
        ),
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["assistant_source"] == "local"
    assert body["provider_category"] == category
    assert "locally" in body["assistant_message"].casefold()
    assert body["configuration"]["hospital_id"] == hospital_id
    assert body["configuration"]["start_date"] == "2027-01-01"
    assert body["configuration"]["end_date"] == "2027-01-03"
    assert body["configuration"]["target_admissions"] == 4
    assert body["configuration"]["target_occupancy_pct"] == 70
    assert body["configuration"]["department_ids"] == [row["id"] for row in departments]
    assert body["retry_after_seconds"] == (30 if category == "quota" else None)
    assert calls["provider"] == 1
    with assistant_client.test_sessions() as db:
        assert db.scalar(select(func.count(GenerationRun.run_id))) == 0


def test_local_fallback_mode_skips_gemini_and_does_not_invent_required_values(assistant_client, monkeypatch):
    workspace_id, _, _ = make_hospital(assistant_client)

    def should_not_call(*_args, **_kwargs):
        raise AssertionError("Gemini must not be called in local fallback mode.")

    monkeypatch.setattr(assistant_service, "interpret_with_gemini", should_not_call)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": "Help configure a dataset for Fictional Generation Hospital.",
        "local_fallback_only": True,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assistant_source"] == "local"
    assert body["provider_category"] == "local_only"
    assert body["status"] == "needs_clarification"
    assert len(body["questions"]) == 4
    assert body["configuration"] is None
    assert "neither AI provider was called" in body["assistant_message"]
    with assistant_client.test_sessions() as db:
        assert db.scalar(select(func.count(GenerationRun.run_id))) == 0


def test_missing_gemini_key_uses_local_fallback(assistant_client, monkeypatch):
    workspace_id, _, _ = make_hospital(assistant_client)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": "Create a dataset for Fictional Generation Hospital.",
    })
    assert response.status_code == 200, response.text
    assert response.json()["assistant_source"] == "local"
    assert response.json()["provider_category"] == "not_configured"
    assert response.json()["status"] == "needs_clarification"


def test_local_fallback_does_not_select_all_for_an_unrecognized_department(assistant_client, monkeypatch):
    workspace_id, _, _ = make_hospital(assistant_client, beds_per_department=2)

    def provider_timeout(*_args, **_kwargs):
        raise HTTPException(status_code=504, detail={"category": "timeout", "message": "Gemini timed out."})

    monkeypatch.setattr(assistant_service, "interpret_with_gemini", provider_timeout)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": (
            "Generate 4 admissions for Fictional Generation Hospital from January 1 to "
            "January 3, 2027, at 70% occupancy for the Neonatology department."
        ),
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "invalid"
    assert body["configuration"] is None
    assert any(error["field"] == "department_names" for error in body["field_errors"])


def _set_department_names(assistant_client, departments, names):
    with assistant_client.test_sessions() as db:
        for department, name in zip(departments, names, strict=True):
            db.get(Department, department["id"]).name = name
        db.commit()


def test_local_fallback_all_active_departments_resolves_scoped_ids_and_preserves_workflow(assistant_client, monkeypatch):
    workspace_id, hospital_id, departments = make_hospital(assistant_client, department_count=2, beds_per_department=5)
    _set_department_names(assistant_client, departments, ["Cardiology", "Neurology"])

    other_hospital = assistant_client.post(
        f"/api/v1/workspaces/{workspace_id}/hospitals",
        json={"name": "Other Fictional Hospital", "code": "OTHER-TEST"},
    ).json()
    other_department = assistant_client.post(
        f"/api/v1/hospitals/{other_hospital['id']}/departments",
        json={"name": "Cardiology", "code": "OTHER-CAR", "bed_capacity": 2},
    ).json()

    def should_not_call_gemini(*_args, **_kwargs):
        raise AssertionError("Local fallback should not require Gemini.")

    monkeypatch.setattr(assistant_service, "interpret_with_gemini", should_not_call_gemini)
    message = (
        "Generate 200 admissions for Fictional Generation Hospital from January 1 to March 31, 2027, "
        "with 75% target occupancy. Use all active departments."
    )
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id, "message": message, "local_fallback_only": True,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    expected_ids = [row["id"] for row in departments]
    assert body["status"] == "ready"
    assert body["assistant_source"] == "local"
    assert body["configuration"]["department_ids"] == expected_ids
    assert other_department["id"] not in body["configuration"]["department_ids"]

    configuration = body["configuration"]
    generation_fields = {key: configuration[key] for key in (
        "start_date", "end_date", "target_admissions", "target_occupancy_pct", "seed", "department_ids",
    )}
    validated = assistant_client.post("/api/v1/assistant/validate-config", json={
        "workspace_id": workspace_id,
        "hospital_id": hospital_id,
        "configuration": generation_fields,
    })
    assert validated.status_code == 200, validated.text
    assert validated.json()["configuration"]["department_ids"] == expected_ids

    preview = assistant_client.post(
        f"/api/v1/hospitals/{hospital_id}/generation-runs/preview",
        json=generation_fields,
    )
    assert preview.status_code == 200, preview.text
    assert [row["department_id"] for row in preview.json()["departments"]] == expected_ids

    follow_up = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": "Set target occupancy of 65%.",
        "local_fallback_only": True,
        "history": [
            {"role": "user", "content": message},
            {"role": "assistant", "content": body["assistant_message"]},
        ],
    })
    assert follow_up.status_code == 200, follow_up.text
    assert follow_up.json()["configuration"]["target_occupancy_pct"] == 65
    assert follow_up.json()["configuration"]["department_ids"] == expected_ids

    with assistant_client.test_sessions() as db:
        assert db.scalar(select(func.count(GenerationRun.run_id))) == 0


@pytest.mark.parametrize(("selection", "expected_indexes"), [
    ("Cardiology and Neurology", [0, 1]),
    ("Emergency", [2]),
])
def test_local_fallback_explicit_department_names_resolve_to_active_ids(assistant_client, selection, expected_indexes):
    workspace_id, _, departments = make_hospital(assistant_client, department_count=3, beds_per_department=2)
    _set_department_names(assistant_client, departments, ["Cardiology", "Neurology", "Emergency"])
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": (
            "Generate 4 admissions for Fictional Generation Hospital from January 1 to January 3, 2027 "
            f"at 70% occupancy for {selection}."
        ),
        "local_fallback_only": True,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["configuration"]["department_ids"] == [departments[index]["id"] for index in expected_indexes]

    empty_selection = assistant_client.post("/api/v1/assistant/validate-config", json={
        "workspace_id": workspace_id,
        "hospital_id": body["configuration"]["hospital_id"],
        "configuration": {
            "start_date": "2027-01-01", "end_date": "2027-01-03", "target_admissions": 4,
            "target_occupancy_pct": 70, "seed": 12, "department_ids": [],
        },
    })
    assert empty_selection.status_code == 422


def test_local_fallback_all_active_departments_with_none_configured_is_clear_error(assistant_client):
    workspace_id, _, departments = make_hospital(assistant_client, beds_per_department=2)
    with assistant_client.test_sessions() as db:
        for row in departments:
            db.get(Department, row["id"]).is_archived = True
        db.commit()

    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": (
            "Generate 4 admissions for Fictional Generation Hospital from January 1 to January 3, 2027 "
            "at 70% occupancy. Use all active departments."
        ),
        "local_fallback_only": True,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "invalid"
    assert body["configuration"] is None
    errors = [item["message"] for item in body["field_errors"] if item["field"] == "department_names"]
    assert errors and "no active departments" in errors[0].casefold()


def test_local_fallback_unknown_department_from_another_hospital_is_not_selected(assistant_client):
    workspace_id, _, _ = make_hospital(assistant_client, beds_per_department=2)
    other_hospital = assistant_client.post(
        f"/api/v1/workspaces/{workspace_id}/hospitals",
        json={"name": "Other Fictional Hospital", "code": "OTHER-TEST"},
    ).json()
    other_department = assistant_client.post(
        f"/api/v1/hospitals/{other_hospital['id']}/departments",
        json={"name": "Oncology", "code": "ONC-01", "bed_capacity": 2},
    ).json()
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": (
            "Generate 4 admissions for Fictional Generation Hospital from January 1 to January 3, 2027 "
            "at 70% occupancy for the Oncology department."
        ),
        "local_fallback_only": True,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "invalid"
    assert body["configuration"] is None
    # The invalid response contains only field names and safe messages, never IDs.
    assert all("id" not in error for error in body["field_errors"])
    assert str(other_department["id"]) not in json.dumps(body["field_errors"])
    assert "active department name" in body["field_errors"][0]["message"]


def test_chat_requests_code_when_hospital_name_is_ambiguous(assistant_client, monkeypatch):
    workspace_id, _, departments = make_hospital(assistant_client)
    duplicate = assistant_client.post(f"/api/v1/workspaces/{workspace_id}/hospitals", json={"name": "Fictional Generation Hospital", "code": "OTHER"})
    assert duplicate.status_code == 201
    patch_proposal(monkeypatch, ready_proposal(departments))
    response = assistant_client.post("/api/v1/assistant/chat", json={"workspace_id": workspace_id, "message": "Generate for Fictional Generation Hospital"})
    assert response.status_code == 200
    assert response.json()["status"] == "needs_clarification"
    assert "code" in response.json()["assistant_message"]
    assert len(response.json()["hospital_choices"]) == 2


def test_chat_rejects_unmatched_department_instead_of_using_model_ids(assistant_client, monkeypatch):
    workspace_id, _, departments = make_hospital(assistant_client)
    patch_proposal(monkeypatch, ready_proposal(departments, department_names=["Invented Department"]))
    response = assistant_client.post("/api/v1/assistant/chat", json={"workspace_id": workspace_id, "message": "Generate at Fictional Generation Hospital"})
    assert response.status_code == 200
    assert response.json()["status"] == "invalid"
    assert response.json()["field_errors"][0]["field"] == "department_names"
    assert response.json()["configuration"] is None


@pytest.mark.parametrize(("update", "field"), [
    ({"start_date": "2027-02-01", "end_date": "2027-01-01"}, "end_date"),
    ({"target_admissions": 5001}, "target_admissions"),
    ({"target_occupancy_pct": 101}, "target_occupancy_pct"),
])
def test_config_validation_reports_field_specific_invalid_values(assistant_client, update, field):
    workspace_id, hospital_id, departments = make_hospital(assistant_client)
    configuration = {"start_date": "2027-01-01", "end_date": "2027-01-03", "target_admissions": 4,
                     "target_occupancy_pct": 70, "seed": 3, "department_ids": [row["id"] for row in departments]}
    configuration.update(update)
    response = assistant_client.post("/api/v1/assistant/validate-config", json={
        "workspace_id": workspace_id, "hospital_id": hospital_id, "configuration": configuration,
    })
    assert response.status_code == 422
    errors = response.json()["detail"]
    if isinstance(errors, dict):
        assert any(item["field"] == field for item in errors["field_errors"])
    else:
        assert any(field in item["loc"] for item in errors)


def test_config_validation_checks_workspace_hospital_department_and_bed_scope(assistant_client):
    workspace_id, hospital_id, departments = make_hospital(assistant_client)
    wrong_workspace = assistant_client.post("/api/v1/workspaces", json={"name": "Other workspace"}).json()["id"]
    base = {"start_date": "2027-01-01", "end_date": "2027-01-03", "target_admissions": 4,
            "target_occupancy_pct": 70, "seed": 3, "department_ids": [departments[0]["id"]]}
    bad_hospital = assistant_client.post("/api/v1/assistant/validate-config", json={
        "workspace_id": wrong_workspace, "hospital_id": hospital_id, "configuration": base,
    })
    assert bad_hospital.status_code == 422
    assert bad_hospital.json()["detail"]["field_errors"][0]["field"] == "hospital_id"
    other_workspace, other_hospital, other_departments = make_hospital(assistant_client)
    other_department_config = {**base, "department_ids": [other_departments[0]["id"]]}
    bad_department = assistant_client.post("/api/v1/assistant/validate-config", json={
        "workspace_id": workspace_id, "hospital_id": hospital_id, "configuration": other_department_config,
    })
    assert bad_department.status_code == 422
    assert bad_department.json()["detail"]["field_errors"][0]["field"] == "department_ids"
    no_beds = assistant_client.post(f"/api/v1/workspaces/{workspace_id}/hospitals", json={"name": "No Beds", "code": "NO-BEDS"}).json()
    no_bed_dept = assistant_client.post(f"/api/v1/hospitals/{no_beds['id']}/departments", json={"name": "Empty", "code": "EMPTY", "bed_capacity": 2}).json()
    no_bed_config = {**base, "department_ids": [no_bed_dept["id"]]}
    missing_bed = assistant_client.post("/api/v1/assistant/validate-config", json={
        "workspace_id": workspace_id, "hospital_id": no_beds["id"], "configuration": no_bed_config,
    })
    assert missing_bed.status_code == 422
    assert missing_bed.json()["detail"]["field_errors"][0]["field"] == "department_ids"


def test_user_edited_configuration_is_revalidated_before_approval(assistant_client):
    workspace_id, hospital_id, departments = make_hospital(assistant_client)
    configuration = {"start_date": "2027-01-01", "end_date": "2027-01-03", "target_admissions": 4,
                     "target_occupancy_pct": 70, "seed": 3, "department_ids": [row["id"] for row in departments]}
    valid = assistant_client.post("/api/v1/assistant/validate-config", json={
        "workspace_id": workspace_id, "hospital_id": hospital_id, "configuration": configuration,
    })
    assert valid.status_code == 200, valid.text
    assert valid.json()["valid"] is True
    assert valid.json()["configuration"]["seed"] == 3
    edited = {**configuration, "target_occupancy_pct": 101}
    invalid = assistant_client.post("/api/v1/assistant/validate-config", json={
        "workspace_id": workspace_id, "hospital_id": hospital_id, "configuration": edited,
    })
    assert invalid.status_code == 422
    assert any("target_occupancy_pct" in issue["loc"] for issue in invalid.json()["detail"])


def test_assistant_missing_key_is_graceful(assistant_client, monkeypatch):
    workspace_id, _, _ = make_hospital(assistant_client)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = assistant_client.post("/api/v1/assistant/chat", json={"workspace_id": workspace_id, "message": "Help configure a dataset."})
    assert response.status_code == 200
    assert response.json()["assistant_source"] == "local"
    assert response.json()["provider_category"] == "not_configured"
    assert response.json()["status"] == "needs_clarification"


@pytest.mark.parametrize(("status_code", "message"), [(429, "rate limit"), (504, "timed out"), (502, "invalid configuration")])
def test_gemini_provider_failures_return_safe_http_errors(assistant_client, monkeypatch, status_code, message):
    workspace_id, _, departments = make_hospital(assistant_client)

    def provider_failure(*_args, **_kwargs):
        from fastapi import HTTPException
        raise HTTPException(status_code=status_code, detail=message)

    monkeypatch.setattr(assistant_service, "interpret_with_gemini", provider_failure)
    response = assistant_client.post("/api/v1/assistant/chat", json={"workspace_id": workspace_id, "message": "Help configure a dataset."})
    assert response.status_code == status_code
    with assistant_client.test_sessions() as db:
        assert db.scalar(select(func.count(GenerationRun.run_id))) == 0


def test_chat_rejects_likely_patient_identifiers_before_model_call(assistant_client, monkeypatch):
    workspace_id, _, _ = make_hospital(assistant_client)

    def should_not_call(*_args, **_kwargs):
        raise AssertionError("The model must not receive likely patient-identifying input.")

    monkeypatch.setattr(assistant_service, "interpret_with_gemini", should_not_call)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": "Generate 10 admissions; patient MRN: 1234567890",
    })
    assert response.status_code == 422
    assert "patient-identifying" in response.json()["detail"]


def test_malformed_gemini_response_is_rejected():
    with pytest.raises(HTTPException) as captured:
        assistant_service._parse_gemini_response(SimpleNamespace(parsed=None, text="{ this is not JSON"))
    assert captured.value.status_code == 502
    assert captured.value.detail["category"] == "malformed_response"


def test_gemini_schema_uses_supported_raw_json_schema_fields():
    from google.genai import types

    pydantic_schema = GeminiGenerationProposal.model_json_schema()
    assert pydantic_schema["additionalProperties"] is False

    schema = assistant_service._gemini_proposal_json_schema()
    assert schema["type"] == "object"
    assert schema["required"] == ["assistant_message"]
    assert schema["properties"]["department_names"] == {"type": "array", "items": {"type": "string"}}

    def keys_deep(value):
        if isinstance(value, dict):
            return set(value).union(*(keys_deep(child) for child in value.values()))
        if isinstance(value, list):
            return set().union(*(keys_deep(child) for child in value)) if value else set()
        return set()

    schema_keys = keys_deep(schema)
    assert "additional_properties" not in schema_keys
    assert "additionalProperties" not in schema_keys

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
    )
    outgoing_config = config.model_dump(by_alias=True, exclude_none=True)
    assert outgoing_config["responseJsonSchema"] == schema
    assert "responseSchema" not in outgoing_config
    assert "response_json_schema" not in outgoing_config
    assert "additional_properties" not in keys_deep(outgoing_config)


def test_gemini_retries_provider_deadline_once_then_returns_structured_response(monkeypatch, caplog):
    from google import genai
    from google.genai.errors import ServerError

    proposal = GeminiGenerationProposal(assistant_message="Please confirm the department selection.")
    deadline = ServerError(504, {"error": {
        "code": 504,
        "status": "DEADLINE_EXCEEDED",
        "message": "Deadline expired before operation could complete.",
    }})

    class FakeModels:
        calls = 0

        def generate_content(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise deadline
            return SimpleNamespace(parsed=proposal, text=None)

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    monkeypatch.setattr(genai, "Client", FakeClient)
    result = assistant_service.interpret_with_gemini("Configure a fictional dataset", [], [], [])
    assert result is proposal
    assert "retrying once" in caplog.text


@pytest.mark.parametrize("raw_text", [None, "{not valid JSON}"])
def test_mocked_gemini_success_and_malformed_structured_response(monkeypatch, raw_text):
    from google import genai

    proposal = GeminiGenerationProposal(assistant_message="Need dates and admission count.")
    captured = {}

    class FakeModels:
        def generate_content(self, **kwargs):
            captured["config"] = kwargs["config"]
            return SimpleNamespace(parsed=proposal if raw_text is None else None, text=raw_text)

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    monkeypatch.setattr(genai, "Client", FakeClient)

    if raw_text is None:
        result = assistant_service.interpret_with_gemini("Configure a dataset", [], [], [])
        assert result is proposal
        assert result.assistant_message == "Need dates and admission count."
    else:
        with pytest.raises(HTTPException) as captured_error:
            assistant_service.interpret_with_gemini("Configure a dataset", [], [], [])
        assert captured_error.value.status_code == 502
        assert captured_error.value.detail["category"] == "malformed_response"
        assert "invalid configuration response" in captured_error.value.detail["message"]

    assert captured["config"].response_json_schema == assistant_service._gemini_proposal_json_schema()


@pytest.mark.parametrize(("status_code", "provider_status", "provider_message", "category", "expected_status"), [
    (401, "UNAUTHENTICATED", "API key is not valid", "authentication", 502),
    (400, "INVALID_ARGUMENT", "API key not valid", "authentication", 502),
    (429, "RESOURCE_EXHAUSTED", "Quota exceeded for PROMPT_SENTINEL-987", "quota", 429),
    (404, "NOT_FOUND", "Configured model was not found", "model_not_found", 502),
    (500, "INTERNAL", "Provider failed for PROMPT_SENTINEL-987", "provider_error", 502),
    (503, "UNAVAILABLE", "Provider temporarily unavailable", "provider_unavailable", 503),
    (504, "DEADLINE_EXCEEDED", "Deadline expired before operation could complete.", "timeout", 504),
])
def test_gemini_sdk_errors_are_diagnosed_and_sanitized(
    monkeypatch, caplog, status_code, provider_status, provider_message, category, expected_status,
):
    from google import genai
    from google.genai.errors import ClientError, ServerError

    secret_key = "AIza" + "A" * 35
    request_prompt = "Generate dataset PROMPT_SENTINEL-987"
    details = {"error": {"code": status_code, "status": provider_status,
                          "message": f"{provider_message}; authorization: Bearer {secret_key}; key={secret_key}; {request_prompt}"}}
    exception_type = ClientError if status_code < 500 else ServerError
    exception = exception_type(status_code, details)
    calls = {"total": 0}

    class FakeModels:
        def generate_content(self, **_kwargs):
            calls["total"] += 1
            config = _kwargs["config"]
            assert config.response_schema is None
            assert config.response_json_schema["type"] == "object"
            assert config.response_json_schema["properties"]["assistant_message"]["type"] == "string"
            assert config.thinking_config.thinking_level.value == "LOW"
            raise exception

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setenv("GEMINI_API_KEY", secret_key)
    monkeypatch.setattr(genai, "Client", FakeClient)
    with pytest.raises(HTTPException) as captured:
        assistant_service.interpret_with_gemini(request_prompt, [], [], [])
    assert captured.value.status_code == expected_status
    assert captured.value.detail["category"] == category
    assert captured.value.detail["message"]
    assert request_prompt not in caplog.text
    assert secret_key not in caplog.text
    assert "Bearer " + secret_key not in caplog.text
    assert f"category={category}" in caplog.text
    assert f"http_status={status_code}" in caplog.text
    assert exception_type.__name__ in caplog.text
    assert provider_message not in caplog.text
    assert calls["total"] == (2 if category == "timeout" else 1)


def test_provider_retry_after_is_bounded_and_available_for_frontend_retry():
    from types import SimpleNamespace

    response = SimpleNamespace(headers={"retry-after": "12.2"})
    assert assistant_service._provider_retry_after_seconds(SimpleNamespace(response=response)) == 13
    retry_details = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7.1s"}]
    assert assistant_service._provider_retry_after_seconds(SimpleNamespace(details=retry_details)) == 8
    assert assistant_service._provider_retry_after_seconds(SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "999999"}))) == 86_400
    mapped = assistant_service._gemini_error_response(SimpleNamespace(
        code=429, status="RESOURCE_EXHAUSTED", message="Quota limit reached", response=response,
    ))
    assert mapped.status_code == 429
    assert mapped.detail["retry_after_seconds"] == 13
    assert mapped.headers["Retry-After"] == "13"


def test_gemini_timeout_and_transport_errors_have_safe_categories(monkeypatch):
    from google import genai

    class FakeModels:
        def __init__(self, error):
            self.error = error

        def generate_content(self, **_kwargs):
            raise self.error

    class FakeClient:
        error = None

        def __init__(self, **_kwargs):
            self.models = FakeModels(self.error)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    monkeypatch.setattr(genai, "Client", FakeClient)
    for error, expected_status, category in [
        (TimeoutError("deadline reached"), 504, "timeout"),
        (RuntimeError("provider unavailable"), 502, "provider_error"),
        (type("ConnectError", (Exception,), {})("All connection attempts failed"), 502, "network_error"),
    ]:
        FakeClient.error = error
        with pytest.raises(HTTPException) as captured:
            assistant_service.interpret_with_gemini("Configure a dataset", [], [], [])
        assert captured.value.status_code == expected_status
        assert captured.value.detail["category"] == category


def test_gemini_success_is_primary_and_groq_is_not_called(assistant_client, monkeypatch):
    workspace_id, _, departments = make_hospital(assistant_client, beds_per_department=2)
    patch_proposal(monkeypatch, ready_proposal(departments))
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-groq-key")

    def groq_must_not_run(*_args, **_kwargs):
        raise AssertionError("Groq must only run if Gemini does not return a valid proposal.")

    monkeypatch.setattr(assistant_service, "interpret_with_groq", groq_must_not_run)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": "Generate 4 admissions for Fictional Generation Hospital from January 1 to January 3, 2027 at 70% occupancy.",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assistant_source"] == "gemini"
    assert body["gemini_status"] == "ready"
    assert body["groq_status"] == "configured"
    with assistant_client.test_sessions() as db:
        assert db.scalar(select(func.count(GenerationRun.run_id))) == 0


@pytest.mark.parametrize("gemini_category", ["provider_unavailable", "quota"])
def test_gemini_failure_falls_back_to_validated_groq(assistant_client, monkeypatch, gemini_category):
    workspace_id, _, departments = make_hospital(assistant_client, beds_per_department=2)
    proposal = ready_proposal(departments)
    calls = []

    def gemini_failure(*_args, **_kwargs):
        raise HTTPException(status_code=429 if gemini_category == "quota" else 503, detail={
            "category": gemini_category,
            "message": "Safe mocked provider failure.",
            "retry_after_seconds": 17 if gemini_category == "quota" else None,
        })

    def groq_success(*_args, **_kwargs):
        calls.append("groq")
        return proposal

    monkeypatch.setenv("GROQ_API_KEY", "unit-test-groq-key")
    monkeypatch.setattr(assistant_service, "interpret_with_gemini", gemini_failure)
    monkeypatch.setattr(assistant_service, "interpret_with_groq", groq_success)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": "Generate 4 admissions for Fictional Generation Hospital from January 1 to January 3, 2027 at 70% occupancy.",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert calls == ["groq"]
    assert body["assistant_source"] == "groq"
    assert body["gemini_status"] == gemini_category
    assert body["groq_status"] == "ready"
    assert body["provider_category"] == gemini_category
    if gemini_category == "quota":
        assert body["retry_after_seconds"] == 17
    assert body["configuration"]["hospital_id"] > 0
    assert body["configuration"]["department_ids"]
    with assistant_client.test_sessions() as db:
        assert db.scalar(select(func.count(GenerationRun.run_id))) == 0


def test_both_providers_failing_uses_local_fallback_once_without_records(assistant_client, monkeypatch):
    workspace_id, _, departments = make_hospital(assistant_client, beds_per_department=2)
    calls = []

    def gemini_failure(*_args, **_kwargs):
        calls.append("gemini")
        raise HTTPException(status_code=503, detail={"category": "provider_unavailable", "message": "Safe."})

    def groq_failure(*_args, **_kwargs):
        calls.append("groq")
        raise HTTPException(status_code=502, detail={"category": "authentication", "message": "Safe."})

    monkeypatch.setenv("GROQ_API_KEY", "unit-test-groq-key")
    monkeypatch.setattr(assistant_service, "interpret_with_gemini", gemini_failure)
    monkeypatch.setattr(assistant_service, "interpret_with_groq", groq_failure)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id,
        "message": "Generate 4 admissions for Fictional Generation Hospital from January 1 to January 3, 2027 at 70% occupancy. Use all active departments.",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert calls == ["gemini", "groq"]
    assert body["assistant_source"] == "local"
    assert body["gemini_status"] == "provider_unavailable"
    assert body["groq_status"] == "authentication"
    assert body["status"] == "ready"
    assert body["configuration"]["department_ids"]
    assert "locally" in body["assistant_message"].casefold() or "explicitly" in body["assistant_message"].casefold()
    with assistant_client.test_sessions() as db:
        assert db.scalar(select(func.count(GenerationRun.run_id))) == 0


def test_groq_authentication_failure_is_categorized_and_local_fallback_remains_safe(assistant_client, monkeypatch):
    workspace_id, _, _ = make_hospital(assistant_client, beds_per_department=2)

    def gemini_unconfigured(*_args, **_kwargs):
        raise AssertionError("Gemini is intentionally not configured for this test.")

    def groq_auth_failure(*_args, **_kwargs):
        raise HTTPException(status_code=502, detail={"category": "authentication", "message": "Safe."})

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-groq-key")
    monkeypatch.setattr(assistant_service, "interpret_with_gemini", gemini_unconfigured)
    monkeypatch.setattr(assistant_service, "interpret_with_groq", groq_auth_failure)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id, "message": "Help configure a dataset for Fictional Generation Hospital.",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["assistant_source"] == "local"
    assert body["gemini_status"] == "not_configured"
    assert body["groq_status"] == "authentication"
    assert body["status"] == "needs_clarification"


def test_groq_missing_key_is_reported_without_request(assistant_client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(HTTPException) as captured:
        assistant_service.interpret_with_groq("Configure a dataset", [], [], [])
    assert captured.value.detail["category"] == "not_configured"


def test_groq_structured_request_uses_configurable_model_and_validates_response(monkeypatch):
    from io import BytesIO

    class FakeResponse:
        def __init__(self, content):
            self.stream = BytesIO(content)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.stream.read()

    proposal_payload = {
        "assistant_message": "Please confirm the missing details.",
        "hospital_name": None,
        "start_date": None,
        "end_date": None,
        "target_admissions": None,
        "target_occupancy_pct": None,
        "seed": None,
        "department_names": None,
    }
    fake_response = FakeResponse(json.dumps({"choices": [{"message": {"content": json.dumps(proposal_payload)}}]}).encode())
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return fake_response

    monkeypatch.setenv("GROQ_API_KEY", "unit-test-groq-key")
    monkeypatch.setenv("GROQ_MODEL", "test/strict-json-model")
    monkeypatch.setattr(assistant_service, "urlopen", fake_urlopen)
    proposal = assistant_service.interpret_with_groq("Configure this fictional dataset", [], [], [])
    body = json.loads(captured["request"].data)
    schema = body["response_format"]["json_schema"]["schema"]
    assert proposal.assistant_message == proposal_payload["assistant_message"]
    assert captured["timeout"] == assistant_service.PROVIDER_TIMEOUT_SECONDS
    assert captured["request"].get_header("Authorization") == "Bearer unit-test-groq-key"
    assert captured["request"].get_header("User-agent") == "BedSynth-AI/1.0"
    assert captured["request"].get_header("User-agent") == assistant_service.GROQ_USER_AGENT
    assert body["model"] == "test/strict-json-model"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False


def test_groq_malformed_structured_response_is_rejected(monkeypatch):
    from io import BytesIO

    class FakeResponse:
        def __init__(self, content):
            self.stream = BytesIO(content)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.stream.read()

    fake_response = FakeResponse(b'{"choices":[{"message":{"content":"{broken"}}]}')
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-groq-key")
    monkeypatch.setattr(assistant_service, "urlopen", lambda *_args, **_kwargs: fake_response)
    with pytest.raises(HTTPException) as captured:
        assistant_service.interpret_with_groq("Configure this fictional dataset", [], [], [])
    assert captured.value.status_code == 502
    assert captured.value.detail["category"] == "malformed_response"


@pytest.mark.parametrize(("status_code", "category"), [
    (401, "authentication"), (403, "authentication"), (429, "quota"),
    (404, "model_not_found"), (503, "provider_unavailable"), (504, "timeout"),
])
def test_groq_http_failures_are_classified_without_returning_provider_body(monkeypatch, caplog, status_code, category):
    from io import BytesIO
    from urllib.error import HTTPError

    secret = "groq-test-secret-that-must-not-be-logged"
    error = HTTPError(
        "https://api.groq.com/openai/v1/chat/completions", status_code, "mock provider error",
        {"retry-after": "11"}, BytesIO(f"request prompt and {secret}".encode()),
    )
    monkeypatch.setenv("GROQ_API_KEY", secret)
    monkeypatch.setattr(assistant_service, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(HTTPException) as captured:
        assistant_service.interpret_with_groq("Safe synthetic configuration", [], [], [])
    assert captured.value.detail["category"] == category
    assert secret not in caplog.text
    if status_code == 429:
        assert captured.value.detail["retry_after_seconds"] == 11


def test_clinical_information_is_rejected_before_either_provider_call(assistant_client, monkeypatch):
    workspace_id, _, _ = make_hospital(assistant_client)

    def provider_must_not_run(*_args, **_kwargs):
        raise AssertionError("Neither provider may receive clinical details.")

    monkeypatch.setenv("GROQ_API_KEY", "unit-test-groq-key")
    monkeypatch.setattr(assistant_service, "interpret_with_gemini", provider_must_not_run)
    monkeypatch.setattr(assistant_service, "interpret_with_groq", provider_must_not_run)
    response = assistant_client.post("/api/v1/assistant/chat", json={
        "workspace_id": workspace_id, "message": "A fictional patient has a diagnosis of pneumonia; generate 5 admissions.",
    })
    assert response.status_code == 422
    assert "clinical information" in response.json()["detail"]
