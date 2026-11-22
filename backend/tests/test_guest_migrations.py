from sqlalchemy import create_engine, event, inspect, text

from app import database
from app import models  # noqa: F401 - register application tables for create_all


def test_guest_session_migration_adds_nullable_owner_without_rewriting_runs(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-guest-schema.db').as_posix()}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE workspaces (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, created_at DATETIME, is_shared BOOLEAN NOT NULL DEFAULT 0)")
        connection.exec_driver_sql("CREATE TABLE hospitals (id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL, code VARCHAR(40), name VARCHAR(160), is_archived BOOLEAN NOT NULL DEFAULT 0, created_at DATETIME)")
        connection.exec_driver_sql("CREATE TABLE generation_runs (run_id VARCHAR(36) PRIMARY KEY, workspace_id INTEGER NOT NULL, hospital_id INTEGER NOT NULL, idempotency_key VARCHAR(36) NOT NULL, config JSON NOT NULL, seed INTEGER NOT NULL, status VARCHAR(20) NOT NULL, started_at DATETIME NOT NULL)")
        connection.exec_driver_sql("INSERT INTO workspaces (id, name, created_at, is_shared) VALUES (9, 'Legacy workspace', '2024-01-01', 1)")
        connection.exec_driver_sql("INSERT INTO hospitals (id, workspace_id, code, name, is_archived, created_at) VALUES (12, 9, 'LEG-12', 'Legacy hospital', 0, '2024-01-01')")
        connection.exec_driver_sql("INSERT INTO generation_runs (run_id, workspace_id, hospital_id, idempotency_key, config, seed, status, started_at) VALUES ('legacy-run', 9, 12, 'legacy-key', '{}', 17, 'completed', '2024-01-02')")
    monkeypatch.setattr(database, "engine", engine)

    database.initialize_database()

    with engine.connect() as connection:
        row = connection.execute(text("SELECT run_id, seed, status, guest_session_id FROM generation_runs WHERE run_id='legacy-run'")).one()
    assert tuple(row) == ("legacy-run", 17, "completed", None)
    assert "guest_session_id" in {column["name"] for column in inspect(engine).get_columns("generation_runs")}
    assert "guest_sessions" in inspect(engine).get_table_names()
    engine.dispose()
