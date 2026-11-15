"""Analytics API coverage over disposable SQLite databases."""

from collections.abc import Generator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app
from app.models import Admission, Bed, BedTransfer, Department, Discharge, OccupancySnapshot
from app.routes import get_db
from test_synthetic_generation import generation_config, make_hospital, preview_and_generate


@pytest.fixture
def analytics_client(tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'analytics-test.db').as_posix()}", connect_args={"check_same_thread": False})
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

    old_lifespan = app.router.lifespan_context
    app.router.lifespan_context = isolated_lifespan
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            client.test_sessions = test_sessions
            yield client
    finally:
        app.dependency_overrides.clear()
        app.router.lifespan_context = old_lifespan
        engine.dispose()


def create_run(client, *, beds_per_department=2, admissions=4, create_beds=True):
    workspace_id, hospital_id, departments = make_hospital(
        client, department_count=2, beds_per_department=beds_per_department, create_beds=create_beds,
    )
    config = generation_config(departments, admissions=admissions, seed=17)
    run = preview_and_generate(client, hospital_id, config)
    return workspace_id, hospital_id, departments, run


def endpoint(client, hospital_id, name, query=""):
    return client.get(f"/api/v1/analytics/hospitals/{hospital_id}/{name}{query}")


def test_overview_uses_persisted_counts_and_latest_run(analytics_client):
    _, hospital_id, _, run = create_run(analytics_client)
    response = endpoint(analytics_client, hospital_id, "overview")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["metadata"]["run_id"] == run["run_id"]
    assert payload["metadata"]["start_date"] == "2025-01-01"
    assert payload["metrics"]["operational_beds"] == 4
    assert payload["metrics"]["admissions"] == run["admissions_count"] == 4
    assert payload["metrics"]["discharges"] == run["discharges_count"] == 4
    assert payload["metrics"]["transfers"] == run["transfers_count"]
    assert payload["metrics"]["occupancy_snapshots"] == run["snapshots_count"] == 6
    assert payload["metrics"]["latest_occupancy_pct"] is not None
    assert payload["metrics"]["average_occupancy_pct"] is not None
    assert payload["metrics"]["peak_occupancy_pct"] is not None


def test_occupancy_daily_rate_and_bed_counts_use_snapshots(analytics_client):
    _, hospital_id, _, run = create_run(analytics_client)
    response = endpoint(analytics_client, hospital_id, "occupancy")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 3
    with analytics_client.test_sessions() as db:
        first_date = db.scalar(select(OccupancySnapshot).where(OccupancySnapshot.run_id == run["run_id"]).order_by(OccupancySnapshot.snapshot_at)).snapshot_at.date()
        snapshots = list(db.scalars(select(OccupancySnapshot).where(OccupancySnapshot.run_id == run["run_id"], func.date(OccupancySnapshot.snapshot_at) == first_date.isoformat())).all())
    first = items[0]
    expected_ops = sum(row.operational_beds for row in snapshots)
    expected_occupied = sum(row.occupied_beds for row in snapshots)
    assert first["date"] == first_date.isoformat()
    assert first["operational_beds"] == expected_ops
    assert first["occupied_beds"] == expected_occupied
    assert first["available_beds"] == sum(row.available_beds for row in snapshots)
    assert first["occupancy_pct"] == pytest.approx(expected_occupied / expected_ops * 100)


def test_patient_flow_days_keep_event_types_separate_and_do_not_add_transfers_to_admissions(analytics_client):
    _, hospital_id, _, run = create_run(analytics_client)
    flow = endpoint(analytics_client, hospital_id, "patient-flow").json()["items"]
    assert sum(row["admissions"] for row in flow) == run["admissions_count"]
    assert sum(row["discharges"] for row in flow) == run["discharges_count"]
    assert sum(row["transfers"] for row in flow) == run["transfers_count"]
    assert sum(row["admissions"] for row in flow) == 4
    assert sum(row["admissions"] for row in flow) != 4 + run["transfers_count"]


def test_department_utilization_is_hospital_and_department_scoped(analytics_client):
    _, hospital_id, departments, _ = create_run(analytics_client)
    all_rows = endpoint(analytics_client, hospital_id, "departments").json()["items"]
    assert {row["department_id"] for row in all_rows} == {item["id"] for item in departments}
    assert all(row["operational_beds"] == 2 for row in all_rows)
    selected = endpoint(analytics_client, hospital_id, "departments", f"?department_id={departments[0]['id']}").json()["items"]
    assert len(selected) == 1 and selected[0]["department_id"] == departments[0]["id"]


def test_analytics_respects_departments_included_in_the_selected_run(analytics_client):
    _, hospital_id, departments = make_hospital(analytics_client, department_count=2, beds_per_department=2)
    config = generation_config(departments, admissions=2)
    config["department_ids"] = [departments[0]["id"]]
    run = preview_and_generate(analytics_client, hospital_id, config)
    overview = endpoint(analytics_client, hospital_id, "overview").json()
    assert overview["metadata"]["run_id"] == run["run_id"]
    assert overview["metrics"]["operational_beds"] == 2
    assert overview["metrics"]["departments_expected"] == 1
    rows = endpoint(analytics_client, hospital_id, "departments").json()["items"]
    assert [row["department_id"] for row in rows] == [departments[0]["id"]]
    outside_scope = endpoint(analytics_client, hospital_id, "overview", f"?department_id={departments[1]['id']}")
    assert outside_scope.status_code == 422


def test_latest_completed_run_is_not_blended_with_earlier_run(analytics_client):
    _, hospital_id, departments, first_run = create_run(analytics_client, admissions=4)
    second_config = generation_config(departments, admissions=2, seed=918)
    second_run = preview_and_generate(analytics_client, hospital_id, second_config)
    response = endpoint(analytics_client, hospital_id, "overview")
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["run_id"] == second_run["run_id"]
    assert response.json()["metadata"]["run_id"] != first_run["run_id"]
    assert response.json()["metrics"]["admissions"] == second_run["admissions_count"] == 2


def test_date_and_department_filters_apply_to_every_metric(analytics_client):
    _, hospital_id, departments, run = create_run(analytics_client)
    filtered = endpoint(
        analytics_client, hospital_id, "overview",
        f"?start_date=2025-01-02&end_date=2025-01-02&department_id={departments[1]['id']}",
    )
    assert filtered.status_code == 200, filtered.text
    data = filtered.json()
    assert data["metrics"]["operational_beds"] == 2
    assert data["metrics"]["occupancy_snapshots"] == 1
    assert data["metrics"]["admissions"] <= run["admissions_count"]
    flow = endpoint(analytics_client, hospital_id, "patient-flow", f"?start_date=2025-01-02&end_date=2025-01-02&department_id={departments[1]['id']}").json()["items"]
    assert len(flow) == 1 and flow[0]["date"] == "2025-01-02"


def test_hospital_isolation_rejects_foreign_department_and_keeps_run_separate(analytics_client):
    _, first_hospital_id, first_departments, _ = create_run(analytics_client, admissions=4)
    _, second_hospital_id, _, second_run = create_run(analytics_client, admissions=2)
    foreign_department = endpoint(analytics_client, first_hospital_id, "overview", f"?department_id={first_departments[0]['id'] + 999}")
    assert foreign_department.status_code == 404
    first = endpoint(analytics_client, first_hospital_id, "overview").json()
    second = endpoint(analytics_client, second_hospital_id, "overview").json()
    assert first["metadata"]["hospital_id"] != second["metadata"]["hospital_id"]
    assert first["metrics"]["admissions"] == 4
    assert second["metadata"]["run_id"] == second_run["run_id"]
    assert second["metrics"]["admissions"] == 2


def test_empty_date_range_returns_empty_series_and_zero_event_totals(analytics_client):
    _, hospital_id, _, _ = create_run(analytics_client)
    query = "?start_date=2026-04-01&end_date=2026-04-03"
    overview = endpoint(analytics_client, hospital_id, "overview", query).json()
    assert overview["metadata"]["has_data"] is False
    assert overview["metrics"]["admissions"] == overview["metrics"]["transfers"] == 0
    assert overview["metrics"]["occupancy_snapshots"] == 0
    assert endpoint(analytics_client, hospital_id, "occupancy", query).json()["items"] == []
    assert endpoint(analytics_client, hospital_id, "patient-flow", query).json()["items"] == []


def test_zero_operational_beds_and_empty_runs_are_safe(analytics_client):
    _, hospital_id, _, _ = create_run(analytics_client, beds_per_department=2, admissions=0, create_beds=False)
    overview = endpoint(analytics_client, hospital_id, "overview").json()
    assert overview["metrics"]["operational_beds"] == 0
    assert overview["metrics"]["latest_occupancy_pct"] is None
    departments = endpoint(analytics_client, hospital_id, "departments").json()["items"]
    assert all(row["operational_beds"] == 0 and row["latest_occupancy_pct"] is None for row in departments)


def test_missing_snapshots_are_not_filled_or_interpolated(analytics_client):
    _, hospital_id, _, run = create_run(analytics_client)
    with analytics_client.test_sessions() as db:
        snapshot = db.scalar(select(OccupancySnapshot).where(OccupancySnapshot.run_id == run["run_id"]).order_by(OccupancySnapshot.snapshot_at))
        db.delete(snapshot)
        db.commit()
    payload = endpoint(analytics_client, hospital_id, "occupancy").json()
    assert len(payload["items"]) == 3
    assert sum(row["snapshot_count"] for row in payload["items"]) == 5
    overview = endpoint(analytics_client, hospital_id, "overview").json()
    assert overview["metrics"]["occupancy_snapshots"] == 5


def test_invalid_date_ranges_and_missing_hospitals_return_http_errors(analytics_client):
    assert endpoint(analytics_client, 9999, "overview").status_code == 404
    _, hospital_id, _, _ = create_run(analytics_client)
    assert endpoint(analytics_client, hospital_id, "overview", "?start_date=2025-01-03&end_date=2025-01-01").status_code == 422
    assert endpoint(analytics_client, hospital_id, "overview", "?start_date=2025-01-01").status_code == 422


def test_exact_run_and_scenario_filters_select_persisted_run(analytics_client):
    _, hospital_id, departments, first = create_run(analytics_client, admissions=4)
    config = generation_config(departments, admissions=2, seed=918)
    config["scenario"] = "high_patient_inflow"
    second = preview_and_generate(analytics_client, hospital_id, config)
    run_options = endpoint(analytics_client, hospital_id, "runs").json()["items"]
    assert [item["run_id"] for item in run_options] == [second["run_id"], first["run_id"]]
    assert run_options[0]["scenario"] == "high_patient_inflow"
    assert run_options[0]["scenario_name"] == "High Patient Inflow"
    selected = endpoint(analytics_client, hospital_id, "overview", f"?run_id={first['run_id']}")
    assert selected.status_code == 200, selected.text
    assert selected.json()["metadata"]["run_id"] == first["run_id"]
    assert selected.json()["metadata"]["scenario"] == "normal_operations"
    scenario = endpoint(analytics_client, hospital_id, "overview", "?scenario=high_patient_inflow")
    assert scenario.status_code == 200 and scenario.json()["metadata"]["run_id"] == second["run_id"]
    mismatch = endpoint(analytics_client, hospital_id, "overview", f"?run_id={first['run_id']}&scenario=low_occupancy")
    assert mismatch.status_code == 422


def test_compare_runs_reports_actual_metrics_metadata_and_percent_changes(analytics_client):
    _, hospital_id, departments, baseline = create_run(analytics_client, admissions=4)
    config = generation_config(departments, admissions=2, seed=918)
    config["scenario"] = "emergency_surge"
    compared = preview_and_generate(analytics_client, hospital_id, config)
    response = analytics_client.post("/api/v1/analytics/runs/compare", json={
        "run_ids": [baseline["run_id"], compared["run_id"]],
        "baseline_run_id": baseline["run_id"],
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["baseline_run_id"] == baseline["run_id"]
    assert [item["run_id"] for item in payload["items"]] == [baseline["run_id"], compared["run_id"]]
    first, second = payload["items"]
    assert first["scenario_name"] == "Normal Operations"
    assert second["scenario_name"] == "Emergency Surge"
    assert first["patient_profile"] == baseline["config"]["request"]["patient_profile"]
    assert first["patients"] == baseline["patients_count"] and second["patients"] == compared["patients_count"]
    patient_difference = compared["patients_count"] - baseline["patients_count"]
    assert second["metrics_vs_baseline"]["patients"] == {
        "absolute_difference": patient_difference,
        "percentage_change": round(patient_difference / baseline["patients_count"] * 100, 2),
    }
    assert second["metrics_vs_baseline"]["average_occupancy_pct"]["percentage_change"] is not None
    assert all(item["occupancy_trend"] for item in payload["items"])
    assert all(item["departments"] for item in payload["items"])


def test_compare_rejects_cross_hospital_or_different_department_scope(analytics_client):
    _, hospital_id, first_departments, first = create_run(analytics_client)
    _, other_hospital, _, other = create_run(analytics_client)
    response = analytics_client.post("/api/v1/analytics/runs/compare", json={"run_ids": [first["run_id"], other["run_id"]]})
    assert response.status_code == 422
    scoped = generation_config(first_departments, admissions=1)
    scoped["department_ids"] = [first_departments[0]["id"]]
    narrowed = preview_and_generate(analytics_client, hospital_id, scoped)
    response = analytics_client.post("/api/v1/analytics/runs/compare", json={"run_ids": [first["run_id"], narrowed["run_id"]]})
    assert response.status_code == 422


def test_department_admission_distribution_and_transfer_activity_use_events(analytics_client):
    _, hospital_id, _, run = create_run(analytics_client, admissions=8)
    response = endpoint(analytics_client, hospital_id, "departments")
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert sum(row["admissions"] for row in rows) == run["admissions_count"]
    assert sum(row["admission_share_pct"] for row in rows) == pytest.approx(100)
    assert sum(row["outgoing_transfers"] for row in rows) == run["transfers_count"]
    assert sum(row["incoming_transfers"] for row in rows) == run["transfers_count"]


def test_rule_based_insights_are_derived_from_metrics_only(analytics_client):
    _, hospital_id, _, run = create_run(analytics_client, admissions=4)
    response = endpoint(analytics_client, hospital_id, "insights")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["run_id"] == run["run_id"]
    assert payload["items"]
    assert all(item["source"] == "calculated_rule" and item["metrics"] for item in payload["items"])
    assert all("synthetic_patient_id" not in item["text"] for item in payload["items"])


def test_analytics_scenario_filter_covers_each_stored_scenario(analytics_client):
    _, hospital_id, departments = make_hospital(analytics_client, department_count=1, beds_per_department=10)
    scenarios = ("normal_operations", "high_patient_inflow", "seasonal_disease_surge", "emergency_surge", "low_occupancy")
    generated = {}
    for index, scenario in enumerate(scenarios):
        config = generation_config(departments, admissions=4, seed=300 + index)
        config["scenario"] = scenario
        generated[scenario] = preview_and_generate(analytics_client, hospital_id, config)
    for scenario in scenarios:
        response = endpoint(analytics_client, hospital_id, "overview", f"?scenario={scenario}")
        assert response.status_code == 200, response.text
        assert response.json()["metadata"]["run_id"] == generated[scenario]["run_id"]
        assert response.json()["metadata"]["scenario"] == scenario


def test_comparison_handles_zero_baseline_and_period_filter_safely(analytics_client):
    _, hospital_id, departments = make_hospital(analytics_client, department_count=1, beds_per_department=3)
    zero = preview_and_generate(analytics_client, hospital_id, generation_config(departments, admissions=0, seed=91))
    positive_config = generation_config(departments, admissions=2, seed=92)
    positive = preview_and_generate(analytics_client, hospital_id, positive_config)
    response = analytics_client.post("/api/v1/analytics/runs/compare", json={
        "run_ids": [zero["run_id"], positive["run_id"]],
        "baseline_run_id": zero["run_id"],
        "start_date": "2025-01-01",
        "end_date": "2025-01-02",
    })
    assert response.status_code == 200, response.text
    baseline, changed = response.json()["items"]
    assert baseline["patients"] == 0
    assert changed["metrics_vs_baseline"]["patients"]["absolute_difference"] == positive["patients_count"]
    assert changed["metrics_vs_baseline"]["patients"]["percentage_change"] is None
    assert baseline["average_occupancy_pct"] == 0
    assert changed["metrics_vs_baseline"]["average_occupancy_pct"]["percentage_change"] is None
    assert changed["average_length_of_stay_hours"] is not None


def test_insights_returns_http_error_when_no_run_matches_filters(analytics_client):
    _, hospital_id, _ = make_hospital(analytics_client, department_count=1)
    response = endpoint(analytics_client, hospital_id, "insights")
    assert response.status_code == 404
