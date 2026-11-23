"""SQLAlchemy database configuration for local SQLite and PostgreSQL deploys."""

import os
from collections.abc import Generator
from pathlib import Path, PurePosixPath

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def configured_database_url(database_url: str | None, app_env: str) -> str:
    """Normalize PostgreSQL URLs and validate persistent production SQLite paths."""
    is_production = app_env.strip().lower() == "production"
    if is_production and not database_url:
        raise RuntimeError("DATABASE_URL must be explicitly configured in production.")

    parsed_url = make_url(database_url or "sqlite:///./bedsynth.db")
    # Neon supplies the standard postgresql:// (and sometimes legacy postgres://)
    # form. Select the declared synchronous psycopg 3 driver explicitly while
    # preserving credentials, SSL options, and all other URL components.
    if parsed_url.get_backend_name() in {"postgres", "postgresql"}:
        parsed_url = parsed_url.set(drivername="postgresql+psycopg")
    # URL.__str__ masks passwords with `***`, so serialize without redaction for
    # SQLAlchemy's internal engine configuration. Never log this value.
    resolved_url = parsed_url.render_as_string(hide_password=False)
    if is_production and parsed_url.get_backend_name() == "sqlite":
        database_path = parsed_url.database
        posix_path = PurePosixPath(database_path) if database_path else None
        path_is_absolute = bool(database_path and (Path(database_path).is_absolute() or posix_path.is_absolute()))
        path_is_on_railway_volume = bool(posix_path and posix_path.is_absolute()
                                        and posix_path != PurePosixPath("/data")
                                        and PurePosixPath("/data") in posix_path.parents)
        if not path_is_absolute or not path_is_on_railway_volume:
            raise RuntimeError(
                "Production SQLite DATABASE_URL must point to a database file beneath the Railway volume at /data."
            )
    return resolved_url


DATABASE_URL = configured_database_url(os.getenv("DATABASE_URL"), os.getenv("APP_ENV", "development"))
_database_backend = make_url(DATABASE_URL).get_backend_name()
connect_args = {"check_same_thread": False} if _database_backend == "sqlite" else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

if _database_backend == "sqlite":
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record) -> None:
        """SQLite leaves FK enforcement off unless it is enabled per connection."""
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Base(DeclarativeBase):
    """Declarative base shared by persisted application models."""


def initialize_database() -> None:
    """Create current tables and safely add columns introduced after the foundation schema."""
    if engine.dialect.name == "sqlite":
        existing = set(inspect(engine).get_table_names())
        legacy_columns = {
            "workspaces": {
                "created_at": "DATETIME",
                "is_shared": "BOOLEAN NOT NULL DEFAULT 0",
            },
            "hospital_networks": {
                "is_archived": "BOOLEAN NOT NULL DEFAULT 0",
            },
            "hospitals": {
                "code": "VARCHAR(40)",
                "is_archived": "BOOLEAN NOT NULL DEFAULT 0",
                "available_to_users": "BOOLEAN NOT NULL DEFAULT 0",
                "created_at": "DATETIME",
            },
            "users": {
                "last_login_at": "DATETIME",
            },
            "departments": {
                "bed_capacity": "INTEGER",
                "is_archived": "BOOLEAN NOT NULL DEFAULT 0",
            },
            "synthetic_patients": {
                "age_years": "INTEGER CHECK (age_years IS NULL OR age_years BETWEEN 0 AND 120)",
                "gender": "VARCHAR(16) CHECK (gender IS NULL OR gender IN ('male', 'female', 'other'))",
            },
            "admissions": {
                "admission_type": "VARCHAR(16) CHECK (admission_type IS NULL OR admission_type IN ('planned', 'emergency'))",
                "requested_at": "DATETIME",
                "scheduled_at": "DATETIME",
                "bed_assigned_at": "DATETIME",
            },
            "generation_runs": {
                "waiting_queue_count": "INTEGER",
                "bed_turnaround_count": "INTEGER",
                "owner_user_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
                "guest_session_id": "INTEGER REFERENCES guest_sessions(id) ON DELETE CASCADE",
                "deleted_at": "DATETIME",
            },
        }
        with engine.begin() as connection:
            for table, additions in legacy_columns.items():
                if table not in existing:
                    continue
                columns = {column["name"] for column in inspect(connection).get_columns(table)}
                for column, declaration in additions.items():
                    if column not in columns:
                        connection.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {declaration}')
            if "hospitals" in existing:
                connection.exec_driver_sql(
                    "UPDATE hospitals SET code = 'HOSP-' || id WHERE code IS NULL OR TRIM(code) = ''"
                )
                connection.exec_driver_sql(
                    "UPDATE hospitals SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
                )
            if "workspaces" in existing:
                connection.exec_driver_sql(
                    "UPDATE workspaces SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
                )

    Base.metadata.create_all(bind=engine)

    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_hospital_workspace_code "
                "ON hospitals (workspace_id, code COLLATE NOCASE)"
            )
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_generation_runs_owner_user_id ON generation_runs (owner_user_id)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_generation_runs_deleted_at ON generation_runs (deleted_at)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_generation_runs_guest_session_id ON generation_runs (guest_session_id)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_workspaces_is_shared ON workspaces (is_shared)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_hospitals_available_to_users ON hospitals (available_to_users)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_users_created_at ON users (created_at)")
