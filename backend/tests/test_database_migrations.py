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
