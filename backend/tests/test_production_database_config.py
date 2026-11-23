import pytest
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateIndex, CreateTable

from app.database import configured_database_url
from app.auth_routes import _registration_day_expression
from app.models import Base, Bed, Department, Hospital, User


def test_production_requires_explicit_database_url() -> None:
    with pytest.raises(RuntimeError, match="explicitly configured"):
        configured_database_url(None, "production")


def test_production_rejects_relative_sqlite_database_path() -> None:
    with pytest.raises(RuntimeError, match="beneath the Railway volume at /data"):
        configured_database_url("sqlite:///./bedsynth.db", "production")


def test_production_rejects_absolute_sqlite_path_outside_the_volume() -> None:
    with pytest.raises(RuntimeError, match="beneath the Railway volume at /data"):
        configured_database_url("sqlite:////tmp/bedsynth.db", "production")


def test_production_accepts_absolute_sqlite_volume_path() -> None:
    assert configured_database_url("sqlite:////data/bedsynth.db", "production") == "sqlite:////data/bedsynth.db"


def test_development_keeps_relative_sqlite_default() -> None:
    assert configured_database_url(None, "development") == "sqlite:///./bedsynth.db"


@pytest.mark.parametrize("scheme", ["postgresql", "postgres"])
def test_neon_postgresql_urls_select_psycopg_and_preserve_connection_options(scheme: str) -> None:
    configured = configured_database_url(
        f"{scheme}://neon_user:private-test-password@ep-example.neon.tech/bedsynth"
        "?sslmode=require&channel_binding=require",
        "production",
    )
    parsed = make_url(configured)
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.username == "neon_user"
    assert parsed.password == "private-test-password"
    assert parsed.host == "ep-example.neon.tech"
    assert parsed.database == "bedsynth"
    assert parsed.query == {"sslmode": "require", "channel_binding": "require"}


def test_explicit_psycopg_url_remains_unchanged() -> None:
    configured = configured_database_url(
        "postgresql+psycopg://neon_user:private-test-password@ep-example.neon.tech/bedsynth?sslmode=require",
        "production",
    )
    parsed = make_url(configured)
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.password == "private-test-password"
    assert parsed.query == {"sslmode": "require"}


@pytest.mark.parametrize("table", [Hospital.__table__, Department.__table__, Bed.__table__, User.__table__])
def test_case_insensitive_columns_compile_for_postgresql(table) -> None:
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert 'COLLATE "NOCASE"' not in ddl


@pytest.mark.parametrize("table", [Hospital.__table__, Department.__table__, Bed.__table__, User.__table__])
def test_sqlite_case_insensitive_column_behavior_is_preserved(table) -> None:
    ddl = str(CreateTable(table).compile(dialect=sqlite.dialect()))
    assert 'COLLATE "NOCASE"' in ddl


def test_case_insensitive_unique_indexes_compile_for_postgresql() -> None:
    required = {
        "uq_users_email_lower",
        "uq_hospitals_workspace_code_lower",
        "uq_departments_hospital_code_lower",
        "uq_beds_hospital_code_lower",
    }
    indexes = {
        index.name: str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for table in (Hospital.__table__, Department.__table__, Bed.__table__, User.__table__)
        for index in table.indexes
    }
    assert required <= indexes.keys()
    assert all("CREATE UNIQUE INDEX" in indexes[name] and "lower(" in indexes[name].lower()
               for name in required)


def test_all_model_tables_and_indexes_compile_for_postgresql() -> None:
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert 'COLLATE "NOCASE"' not in ddl
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize(
    "backend, expected_sql",
    [("sqlite", "date(users.created_at)"), ("postgresql", "timezone")],
)
def test_registration_activity_utc_day_expression_is_dialect_compatible(backend: str, expected_sql: str) -> None:
    fake_session = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name=backend)))
    expression = _registration_day_expression(fake_session)
    dialect = postgresql.dialect() if backend == "postgresql" else None
    statement = select(expression)
    sql = str(statement.compile(dialect=dialect)) if dialect is not None else str(statement)
    assert expected_sql in sql.lower()
