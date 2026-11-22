from sqlalchemy import create_engine, inspect, text

from app import database


def test_initialize_database_adds_nullable_arrival_columns_without_rewriting_legacy_rows(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-schema.db').as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE admissions (id INTEGER PRIMARY KEY, admitted_at DATETIME NOT NULL)")
        connection.exec_driver_sql("INSERT INTO admissions (id, admitted_at) VALUES (7, '2024-05-06 12:30:00')")
    monkeypatch.setattr(database, "engine", engine)

    database.initialize_database()

    with engine.connect() as connection:
        row = connection.execute(text("SELECT id, admitted_at, admission_type, requested_at, scheduled_at, bed_assigned_at FROM admissions WHERE id = 7")).one()
    assert row.id == 7
    assert row.admitted_at == "2024-05-06 12:30:00"
    assert row.admission_type is None
    assert row.requested_at is None
    assert row.scheduled_at is None
    assert row.bed_assigned_at is None
    assert {column["name"] for column in inspect(engine).get_columns("admissions")} >= {
        "admission_type", "requested_at", "scheduled_at", "bed_assigned_at",
    }
    engine.dispose()


def test_initialize_database_adds_login_tracking_and_activity_table_without_rewriting_users(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-users.db').as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(254) NOT NULL, password_hash VARCHAR(256) NOT NULL, "
            "role VARCHAR(16) NOT NULL, is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO users (id,email,password_hash,role,is_active,created_at) "
            "VALUES (41,'preserved@example.test','opaque-hash','user',1,'2024-06-01 12:00:00')"
        )
    monkeypatch.setattr(database, "engine", engine)

    database.initialize_database()

    with engine.connect() as connection:
        row = connection.execute(text("SELECT id,email,created_at,last_login_at FROM users WHERE id=41")).one()
    assert (row.id, row.email, row.created_at, row.last_login_at) == (41, "preserved@example.test", "2024-06-01 12:00:00", None)
    assert "account_activity_events" in inspect(engine).get_table_names()
    indexes = {index["name"] for index in inspect(engine).get_indexes("account_activity_events")}
    assert {"ix_account_activity_occurred_at", "ix_account_activity_target_time",
            "ix_account_activity_actor_time", "ix_account_activity_type_time"} <= indexes
    engine.dispose()


def test_initialize_database_adds_default_unpublished_flag_without_rewriting_hospitals(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-hospital.db').as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE workspaces (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL)")
        connection.exec_driver_sql("INSERT INTO workspaces (id, name) VALUES (9, 'Legacy workspace')")
        connection.exec_driver_sql(
            "CREATE TABLE hospitals (id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL, name VARCHAR(160) NOT NULL, code VARCHAR(40), is_archived BOOLEAN NOT NULL DEFAULT 0)"
        )
        connection.exec_driver_sql(
            "INSERT INTO hospitals (id, workspace_id, name, code, is_archived) VALUES (13, 9, 'Sunrise General Hospital', 'SUNRISE', 0)"
        )
    monkeypatch.setattr(database, "engine", engine)

    database.initialize_database()

    with engine.connect() as connection:
        row = connection.execute(text("SELECT id, workspace_id, name, code, is_archived, available_to_users FROM hospitals WHERE id = 13")).one()
    assert (row.id, row.workspace_id, row.name, row.code, row.is_archived, row.available_to_users) == (
        13, 9, "Sunrise General Hospital", "SUNRISE", 0, 0,
    )
    engine.dispose()
