"""SQLite engine and SQLAlchemy base configuration."""

import os

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bedsynth.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record) -> None:
        """SQLite leaves FK enforcement off unless it is enabled per connection."""
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Declarative base shared by persisted application models."""


def initialize_database() -> None:
    """Create current tables and safely add columns introduced after the foundation schema."""
    if engine.dialect.name == "sqlite":
        existing = set(inspect(engine).get_table_names())
        legacy_columns = {
            "workspaces": {
                "created_at": "DATETIME",
            },
            "hospital_networks": {
                "is_archived": "BOOLEAN NOT NULL DEFAULT 0",
            },
            "hospitals": {
                "code": "VARCHAR(40)",
                "is_archived": "BOOLEAN NOT NULL DEFAULT 0",
                "created_at": "DATETIME",
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
