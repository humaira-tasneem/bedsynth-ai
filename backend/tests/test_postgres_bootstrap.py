from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap_production import (
    BOOTSTRAP_ADMIN_EMAIL,
    BOOTSTRAP_ADMIN_PASSWORD,
    FRONTEND_ORIGINS,
    BootstrapRefused,
)
from app.bootstrap_postgres import (
    APP_ENV,
    DATABASE_URL,
    POSTGRES_BOOTSTRAP_ENABLED,
    initialize_neon_database,
    validate_neon_bootstrap_environment,
    validate_neon_engine_target,
)
from app.models import (
    Base,
    Bed,
    Department,
    Hospital,
    ProductionBootstrapRecord,
    User,
    Workspace,
)


def neon_environment(**overrides: str) -> dict[str, str]:
    environment = {
        POSTGRES_BOOTSTRAP_ENABLED: "true",
        APP_ENV: "production",
        DATABASE_URL: "postgresql://neon_user:placeholder@ep-test.neon.tech/bedsynth?sslmode=require",
        FRONTEND_ORIGINS: "https://bedsynth.example.test",
        BOOTSTRAP_ADMIN_EMAIL: "admin@example.test",
        BOOTSTRAP_ADMIN_PASSWORD: "long-safe-test-password",
    }
    environment.update(overrides)
    return environment


class NeonEngineIdentity:
    """Expose the Neon target identity while using an isolated SQLite test DB."""

    def __init__(self, sqlite_engine) -> None:
        self.url = make_url(
            "postgresql+psycopg://neon_user:placeholder@ep-test.neon.tech/bedsynth?sslmode=require"
        )
        self.dialect = SimpleNamespace(name="postgresql", driver="psycopg")
        self._sqlite_engine = sqlite_engine

    def connect(self):
        return self._sqlite_engine.connect()


@pytest.fixture
def isolated_database(tmp_path) -> Generator:
    engine = create_engine(f"sqlite:///{(tmp_path / 'neon-bootstrap-test.db').as_posix()}")
    wrapped_engine = NeonEngineIdentity(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield engine, wrapped_engine, factory
    engine.dispose()


def test_valid_neon_configuration_is_parsed_without_retaining_credentials() -> None:
    config = validate_neon_bootstrap_environment(neon_environment())

    assert config.host == "ep-test.neon.tech"
    assert config.database == "bedsynth"
    assert config.username == "neon_user"
    assert config.sslmode == "require"
    assert "placeholder" not in repr(config)


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({POSTGRES_BOOTSTRAP_ENABLED: "false"}, POSTGRES_BOOTSTRAP_ENABLED),
        ({APP_ENV: "development"}, "APP_ENV must be production"),
        ({DATABASE_URL: "sqlite:////data/bedsynth.db"}, "Neon PostgreSQL only"),
        ({DATABASE_URL: "postgresql://u:p@railway.internal/bedsynth?sslmode=require"}, "Neon PostgreSQL"),
        ({DATABASE_URL: "postgresql://u:p@ep-test.neon.tech/bedsynth"}, "require TLS"),
        ({FRONTEND_ORIGINS: "*"}, "exact HTTPS origins"),
        ({FRONTEND_ORIGINS: "http://bedsynth.example.test"}, "exact HTTPS origins"),
    ],
)
def test_unsafe_or_incomplete_neon_environment_is_refused(overrides, expected) -> None:
    with pytest.raises(BootstrapRefused, match=expected):
        validate_neon_bootstrap_environment(neon_environment(**overrides))


def test_neon_engine_target_must_match_validated_host_database_user_and_tls() -> None:
    config = validate_neon_bootstrap_environment(neon_environment())

    class WrongEngine:
        url = make_url("postgresql+psycopg://other:secret@other.neon.tech/other?sslmode=require")
        dialect = SimpleNamespace(name="postgresql", driver="psycopg")

    with pytest.raises(BootstrapRefused, match="does not match"):
        validate_neon_engine_target(WrongEngine(), config)


def test_fresh_neon_bootstrap_seeds_four_hospitals_and_repeat_is_noop(isolated_database) -> None:
    sqlite_engine, neon_engine, factory = isolated_database
    environment = neon_environment()

    def initialize_schema() -> None:
        Base.metadata.create_all(bind=sqlite_engine)

    assert initialize_neon_database(
        validate_neon_bootstrap_environment(environment), environment,
        neon_engine, factory, initialize_schema,
    ) is True
    with factory() as db:
        assert db.scalar(select(func.count(User.id))) == 1
        original_password_hash = db.scalar(select(User.password_hash))
        assert db.scalar(select(func.count(Hospital.id))) == 4
        assert db.scalar(select(func.count(Department.id))) == 21
        assert db.scalar(select(func.count(Bed.id))) == 480
        assert db.scalar(select(func.count(Hospital.id)).where(Hospital.available_to_users.is_(True))) == 0
        assert db.scalar(select(func.count(ProductionBootstrapRecord.id))) == 1

    # Completed bootstrap is a no-op even if one-time credential variables have
    # already been removed from the deployment environment.
    environment.pop(BOOTSTRAP_ADMIN_EMAIL)
    environment.pop(BOOTSTRAP_ADMIN_PASSWORD)
    assert initialize_neon_database(
        validate_neon_bootstrap_environment(environment), environment,
        neon_engine, factory, lambda: pytest.fail("schema initialization must not rerun"),
    ) is False
    with factory() as db:
        assert db.scalar(select(func.count(User.id))) == 1
        assert db.scalar(select(User.password_hash)) == original_password_hash
        assert db.scalar(select(func.count(Hospital.id))) == 4
        assert db.scalar(select(func.count(ProductionBootstrapRecord.id))) == 1


def test_existing_application_data_refuses_without_schema_or_record_changes(isolated_database) -> None:
    sqlite_engine, neon_engine, factory = isolated_database
    Base.metadata.create_all(bind=sqlite_engine)
    with factory() as db:
        db.add(Workspace(name="Existing workspace"))
        db.commit()

    with pytest.raises(BootstrapRefused, match="existing application data"):
        initialize_neon_database(
            validate_neon_bootstrap_environment(neon_environment()), neon_environment(),
            neon_engine, factory, lambda: pytest.fail("existing schema must not be initialized"),
        )
    with factory() as db:
        assert db.scalar(select(func.count(Workspace.id))) == 1
        assert db.scalar(select(func.count(User.id))) == 0
        assert db.scalar(select(func.count(ProductionBootstrapRecord.id))) == 0


def test_bootstrap_transaction_rolls_back_admin_seed_and_marker_on_failure(isolated_database, monkeypatch) -> None:
    sqlite_engine, neon_engine, factory = isolated_database
    environment = neon_environment()

    def initialize_schema() -> None:
        Base.metadata.create_all(bind=sqlite_engine)

    def fail_schema_seed(db: Session) -> None:
        db.add(Workspace(name="Partial data"))
        db.flush()
        raise RuntimeError("test-only simulated seed failure")

    # Exercise the production transaction helper with an injected failing seed.
    def failing_bootstrap(db, email, password, seed_function=None):
        return original(db, email, password, seed_function=fail_schema_seed)

    import app.bootstrap_postgres as module

    original = module.bootstrap_database
    monkeypatch.setattr(module, "bootstrap_database", failing_bootstrap)
    with pytest.raises(RuntimeError, match="simulated seed failure"):
        initialize_neon_database(
            validate_neon_bootstrap_environment(environment), environment,
            neon_engine, factory, initialize_schema,
        )

    with factory() as db:
        assert db.scalar(select(func.count(User.id))) == 0
        assert db.scalar(select(func.count(Workspace.id))) == 0
        assert db.scalar(select(func.count(ProductionBootstrapRecord.id))) == 0
