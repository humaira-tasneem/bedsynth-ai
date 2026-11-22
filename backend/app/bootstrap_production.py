"""Explicit, one-time bootstrap for a fresh Railway production database.

Run with the bootstrap environment enabled from the backend service container.
Administrator credentials are read only from environment variables and are
never included in command-line arguments or output.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.environment import load_backend_environment


BOOTSTRAP_ENABLED = "BEDSY_AI_PRODUCTION_BOOTSTRAP_ENABLED"
BOOTSTRAP_ADMIN_EMAIL = "BEDSY_AI_BOOTSTRAP_ADMIN_EMAIL"
BOOTSTRAP_ADMIN_PASSWORD = "BEDSY_AI_BOOTSTRAP_ADMIN_PASSWORD"
DATABASE_URL = "DATABASE_URL"
APP_ENV = "APP_ENV"
FRONTEND_ORIGINS = "FRONTEND_ORIGINS"
EXPECTED_DATABASE_URL = "sqlite:////data/bedsynth.db"
BOOTSTRAP_MARKER_TABLE = "production_bootstrap_records"


class BootstrapRefused(RuntimeError):
    """A safe precondition failure with no credential or row-value details."""


@dataclass(frozen=True, repr=False)
class BootstrapRuntimeConfig:
    database_url: str


def validate_bootstrap_environment(environ: Mapping[str, str]) -> BootstrapRuntimeConfig:
    """Require an explicit production opt-in and the exact Railway DB/origin config."""
    if environ.get(BOOTSTRAP_ENABLED, "").strip().lower() != "true":
        raise BootstrapRefused(f"Set {BOOTSTRAP_ENABLED}=true for this one-time command.")
    if environ.get(APP_ENV, "").strip().lower() != "production":
        raise BootstrapRefused("APP_ENV must be production.")

    database_url = environ.get(DATABASE_URL, "").strip()
    try:
        parsed_url = make_url(database_url)
    except Exception:
        raise BootstrapRefused(f"DATABASE_URL must be {EXPECTED_DATABASE_URL}.") from None
    if (parsed_url.drivername != "sqlite" or parsed_url.database != "/data/bedsynth.db"
            or parsed_url.query):
        raise BootstrapRefused(f"DATABASE_URL must be {EXPECTED_DATABASE_URL}.")

    origins = environ.get(FRONTEND_ORIGINS, "").strip()
    if not origins:
        raise BootstrapRefused("FRONTEND_ORIGINS must contain the exact deployed HTTPS frontend origin.")
    try:
        from app.auth import configured_frontend_origins

        configured_frontend_origins("production", origins, None)
    except Exception:
        raise BootstrapRefused("FRONTEND_ORIGINS must contain exact HTTPS origins without wildcards or paths.") from None
    return BootstrapRuntimeConfig(database_url=database_url)


def validate_admin_credentials(email: str | None, password: str | None) -> tuple[str, str]:
    """Validate bootstrap credentials using the regular registration limits."""
    from app.auth import normalize_email

    normalized_email = normalize_email(email or "")
    if (not 3 <= len(normalized_email) <= 254
            or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized_email)):
        raise BootstrapRefused("The bootstrap administrator email is invalid.")
    if password is None or not 12 <= len(password) <= 128:
        raise BootstrapRefused("The bootstrap administrator password must be 12 to 128 characters.")
    return normalized_email, password


def _table_has_rows(connection: Connection, table_name: str) -> bool:
    safe_name = table_name.replace('"', '""')
    return connection.exec_driver_sql(f'SELECT 1 FROM "{safe_name}" LIMIT 1').first() is not None


def _completed_marker_exists(connection: Connection) -> bool:
    tables = set(inspect(connection).get_table_names())
    if BOOTSTRAP_MARKER_TABLE not in tables:
        return False
    return _table_has_rows(connection, BOOTSTRAP_MARKER_TABLE)


def _assert_fresh_database(connection: Connection) -> None:
    tables = set(inspect(connection).get_table_names())
    if "users" in tables and _table_has_rows(connection, "users"):
        raise BootstrapRefused("The database already contains user accounts; bootstrap requires a fresh database.")

    for table in sorted(tables):
        if table.startswith("sqlite_") or table == BOOTSTRAP_MARKER_TABLE or table == "users":
            continue
        if _table_has_rows(connection, table):
            raise BootstrapRefused("The database contains existing application data; bootstrap requires a fresh database.")


def prepare_database_for_bootstrap(engine: Engine, initialize_schema: Callable[[], None]) -> bool:
    """Check the untouched database before migrations; then initialize its schema.

    Returns False when the persistent completion marker already exists.
    """
    with engine.connect() as connection:
        if _completed_marker_exists(connection):
            return False
        _assert_fresh_database(connection)
    initialize_schema()
    return True


def bootstrap_database(
    db: Session,
    email: str | None,
    password: str | None,
    seed_function: Callable[[Session], object] | None = None,
) -> bool:
    """Create the administrator, demo configuration, and marker atomically."""
    from app.auth import hash_password
    from app.models import ProductionBootstrapRecord, User

    try:
        with db.begin():
            completed = db.get(ProductionBootstrapRecord, 1)
            if completed is not None:
                return False

            _assert_fresh_database(db.connection())
            normalized_email, administrator_password = validate_admin_credentials(email, password)
            administrator = User(
                email=normalized_email,
                password_hash=hash_password(administrator_password),
                role="admin",
                is_active=True,
            )
            db.add(administrator)
            db.flush()

            if seed_function is None:
                from app.demo_seed import seed_demo_hospitals

                seed_function = seed_demo_hospitals
            seed_function(db)
            db.add(ProductionBootstrapRecord(id=1, admin_user_id=administrator.id))
            db.flush()
        return True
    except IntegrityError:
        raise BootstrapRefused("Bootstrap conflicted with another database write; no bootstrap records were committed.") from None


def run_bootstrap(environ: Mapping[str, str] | None = None) -> bool:
    """Run the production checks and bootstrap using the configured DB session."""
    config = validate_bootstrap_environment(environ if environ is not None else os.environ)
    volume = Path("/data")
    if not volume.is_dir():
        raise BootstrapRefused("The Railway persistent volume must be mounted at /data before bootstrapping.")

    # Register all ORM models (including the bootstrap marker) with the shared
    # declarative metadata before initialize_database() creates missing tables.
    import app.models  # noqa: F401
    from app.database import SessionLocal, engine, initialize_database

    actual_url = make_url(str(engine.url))
    if actual_url.drivername != "sqlite" or actual_url.database != "/data/bedsynth.db" or actual_url.query:
        raise BootstrapRefused("The backend database engine is not configured for /data/bedsynth.db.")

    if not prepare_database_for_bootstrap(engine, initialize_database):
        return False

    with SessionLocal() as db:
        return bootstrap_database(
            db,
            (environ if environ is not None else os.environ).get(BOOTSTRAP_ADMIN_EMAIL),
            (environ if environ is not None else os.environ).get(BOOTSTRAP_ADMIN_PASSWORD),
        )


def main() -> int:
    load_backend_environment()
    try:
        completed = run_bootstrap()
        if completed:
            print("Production bootstrap completed: administrator and fictional demo hospitals initialized.")
        else:
            print("Production bootstrap was already completed; no changes were made.")
        return 0
    except BootstrapRefused as exc:
        print(f"Production bootstrap refused: {exc}", file=sys.stderr)
        return 1
    except Exception:
        # Do not print exception text or a traceback: driver errors can contain
        # SQL parameters or persisted values. Detailed diagnostics must be
        # added only if they are proven to exclude credentials and row data.
        print("Production bootstrap failed safely; no credentials or database values were logged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
