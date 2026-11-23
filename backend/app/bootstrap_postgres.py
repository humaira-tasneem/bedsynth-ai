"""One-time, fail-closed bootstrap for a fresh Neon PostgreSQL database."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap_production import (
    APP_ENV,
    BOOTSTRAP_ADMIN_EMAIL,
    BOOTSTRAP_ADMIN_PASSWORD,
    DATABASE_URL,
    FRONTEND_ORIGINS,
    BootstrapRefused,
    bootstrap_database,
    prepare_database_for_bootstrap,
)
from app.environment import load_backend_environment


POSTGRES_BOOTSTRAP_ENABLED = "BEDSY_AI_POSTGRES_BOOTSTRAP_ENABLED"


@dataclass(frozen=True, repr=False)
class NeonBootstrapConfig:
    host: str
    database: str
    username: str
    port: int | None
    sslmode: str


def _is_neon_host(host: str | None) -> bool:
    normalized = (host or "").strip().lower().rstrip(".")
    return normalized.endswith(".neon.tech")


def validate_neon_bootstrap_environment(environ: Mapping[str, str]) -> NeonBootstrapConfig:
    """Require explicit opt-in and a TLS-enabled Neon PostgreSQL URL."""
    if environ.get(POSTGRES_BOOTSTRAP_ENABLED, "").strip().lower() != "true":
        raise BootstrapRefused(f"Set {POSTGRES_BOOTSTRAP_ENABLED}=true for this one-time command.")
    if environ.get(APP_ENV, "").strip().lower() != "production":
        raise BootstrapRefused("APP_ENV must be production.")

    raw_url = environ.get(DATABASE_URL, "").strip()
    try:
        parsed = make_url(raw_url)
    except Exception:
        raise BootstrapRefused("DATABASE_URL must be a valid Neon PostgreSQL connection URL.") from None
    if parsed.get_backend_name() not in {"postgres", "postgresql"}:
        raise BootstrapRefused("This command accepts Neon PostgreSQL only; SQLite and other databases are refused.")
    if not _is_neon_host(parsed.host) or not parsed.database or not parsed.username:
        raise BootstrapRefused("DATABASE_URL must target a Neon PostgreSQL database with a database and user.")

    sslmode = str(parsed.query.get("sslmode", "")).strip().lower()
    if sslmode not in {"require", "verify-ca", "verify-full"}:
        raise BootstrapRefused("DATABASE_URL must require TLS with sslmode=require or stronger.")

    origins = environ.get(FRONTEND_ORIGINS, "").strip()
    if not origins:
        raise BootstrapRefused("FRONTEND_ORIGINS must contain the deployed HTTPS frontend origin.")
    try:
        from app.auth import configured_frontend_origins

        configured_frontend_origins("production", origins, None)
    except Exception:
        raise BootstrapRefused("FRONTEND_ORIGINS must contain exact HTTPS origins without wildcards or paths.") from None

    return NeonBootstrapConfig(
        host=parsed.host.lower().rstrip("."),
        database=parsed.database,
        username=parsed.username,
        port=parsed.port,
        sslmode=sslmode,
    )


def validate_neon_engine_target(engine: Engine, config: NeonBootstrapConfig) -> None:
    """Ensure the actual SQLAlchemy engine matches the validated Neon target."""
    url: URL = engine.url
    if (
        engine.dialect.name != "postgresql"
        or engine.dialect.driver != "psycopg"
        or not _is_neon_host(url.host)
        or url.host.lower().rstrip(".") != config.host
        or url.database != config.database
        or url.username != config.username
        or url.port != config.port
        or str(url.query.get("sslmode", "")).lower() != config.sslmode
    ):
        raise BootstrapRefused("The configured database engine does not match the validated Neon PostgreSQL target.")


def initialize_neon_database(
    config: NeonBootstrapConfig,
    environ: Mapping[str, str],
    engine: Engine,
    session_factory: sessionmaker[Session],
    initialize_schema: Callable[[], None],
) -> bool:
    """Initialize an empty Neon database, then atomically create admin and demos.

    A persisted ProductionBootstrapRecord makes subsequent calls no-ops. The
    existing preflight refuses any non-empty application table before schema
    initialization, and bootstrap_database commits the admin, demo seed, and
    marker as one transaction.
    """
    validate_neon_engine_target(engine, config)
    if not prepare_database_for_bootstrap(engine, initialize_schema):
        return False

    with session_factory() as db:
        return bootstrap_database(
            db,
            environ.get(BOOTSTRAP_ADMIN_EMAIL),
            environ.get(BOOTSTRAP_ADMIN_PASSWORD),
        )


def run_postgres_bootstrap(environ: Mapping[str, str] | None = None) -> bool:
    source = environ if environ is not None else os.environ
    config = validate_neon_bootstrap_environment(source)

    # Register the complete metadata before create_all initializes a fresh
    # database. Environment loading in main() happens before database import.
    import app.models  # noqa: F401
    from app.database import SessionLocal, engine, initialize_database

    return initialize_neon_database(config, source, engine, SessionLocal, initialize_database)


def main() -> int:
    load_backend_environment()
    try:
        completed = run_postgres_bootstrap()
        if completed:
            print("Neon PostgreSQL bootstrap completed: administrator and fictional demo hospitals initialized.")
        else:
            print("Neon PostgreSQL bootstrap was already completed; no changes were made.")
        return 0
    except BootstrapRefused as exc:
        print(f"Neon PostgreSQL bootstrap refused: {exc}", file=sys.stderr)
        return 1
    except Exception:
        # Do not include exception text or a traceback because DB driver errors
        # may contain connection details or SQL parameters.
        print("Neon PostgreSQL bootstrap failed safely; credentials and database values were not logged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
