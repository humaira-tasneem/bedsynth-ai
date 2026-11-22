from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app import database
import app.bootstrap_production as bootstrap_module
from app.auth import verify_password
from app.bootstrap_production import (
    APP_ENV,
    BOOTSTRAP_ADMIN_EMAIL,
    BOOTSTRAP_ADMIN_PASSWORD,
    BOOTSTRAP_ENABLED,
    DATABASE_URL,
    FRONTEND_ORIGINS,
    BootstrapRefused,
    bootstrap_database,
    prepare_database_for_bootstrap,
    validate_admin_credentials,
    validate_bootstrap_environment,
)
from app.models import (
    Base,
    Bed,
    Department,
    GenerationRun,
    Hospital,
    ProductionBootstrapRecord,
    User,
    Workspace,
)


@pytest.fixture
def bootstrap_engine(tmp_path) -> Generator:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'bootstrap.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    yield engine
    engine.dispose()


@pytest.fixture
def bootstrap_db(bootstrap_engine) -> Generator[Session, None, None]:
    Base.metadata.create_all(bind=bootstrap_engine)
    factory = sessionmaker(bind=bootstrap_engine, autoflush=False, autocommit=False)
    with factory() as db:
        yield db


def _counts(db: Session) -> tuple[int, int, int, int]:
    return (
        db.scalar(select(func.count(User.id))) or 0,
        db.scalar(select(func.count(Hospital.id))) or 0,
        db.scalar(select(func.count(Department.id))) or 0,
        db.scalar(select(func.count(Bed.id))) or 0,
    )


def test_fresh_bootstrap_creates_admin_and_four_unpublished_demo_hospitals(bootstrap_db: Session) -> None:
    assert bootstrap_database(bootstrap_db, "Admin@Example.test", "long-safe-test-password") is True

    admin = bootstrap_db.scalar(select(User))
    assert admin is not None
    assert admin.email == "admin@example.test"
    assert admin.role == "admin" and admin.is_active is True
    assert verify_password("long-safe-test-password", admin.password_hash)
    assert bootstrap_db.scalar(select(func.count(Hospital.id))) == 4
    assert bootstrap_db.scalar(select(func.count(Department.id))) == 21
    assert bootstrap_db.scalar(select(func.count(Bed.id))) == 480
    assert bootstrap_db.scalar(select(func.count(Hospital.id)).where(Hospital.available_to_users.is_(True))) == 0
    assert bootstrap_db.get(ProductionBootstrapRecord, 1).admin_user_id == admin.id


def test_existing_user_account_refuses_bootstrap_without_modification(bootstrap_db: Session) -> None:
    existing = User(email="user@example.test", password_hash="unchanged-hash", role="user")
    bootstrap_db.add(existing)
    bootstrap_db.commit()

    with pytest.raises(BootstrapRefused, match="already contains user accounts"):
        bootstrap_database(bootstrap_db, "admin@example.test", "long-safe-test-password")

    assert _counts(bootstrap_db) == (1, 0, 0, 0)
    assert existing.role == "user" and existing.password_hash == "unchanged-hash"
    assert bootstrap_db.get(ProductionBootstrapRecord, 1) is None


def test_existing_operational_data_refuses_bootstrap(bootstrap_db: Session) -> None:
    workspace = Workspace(name="Existing workspace")
    bootstrap_db.add(workspace)
    bootstrap_db.flush()
    hospital = Hospital(workspace_id=workspace.id, name="Existing hospital", code="OLD-1")
    bootstrap_db.add(hospital)
    bootstrap_db.flush()
    run = GenerationRun(
        run_id="legacy-run",
        workspace_id=workspace.id,
        hospital_id=hospital.id,
        idempotency_key="legacy-key",
        config={},
        seed=1,
    )
    bootstrap_db.add(run)
    bootstrap_db.commit()

    with pytest.raises(BootstrapRefused, match="existing application data"):
        bootstrap_database(bootstrap_db, "admin@example.test", "long-safe-test-password")

    assert bootstrap_db.get(GenerationRun, "legacy-run") is not None
    assert _counts(bootstrap_db) == (0, 1, 0, 0)
    assert bootstrap_db.get(ProductionBootstrapRecord, 1) is None


def test_success_marker_makes_second_execution_a_no_op(bootstrap_db: Session) -> None:
    assert bootstrap_database(bootstrap_db, "admin@example.test", "long-safe-test-password") is True
    first_counts = _counts(bootstrap_db)
    bootstrap_db.rollback()

    # Credentials are intentionally not needed after a completed bootstrap.
    assert bootstrap_database(bootstrap_db, None, None) is False
    assert _counts(bootstrap_db) == first_counts == (1, 4, 21, 480)
    assert bootstrap_db.scalar(select(func.count(ProductionBootstrapRecord.id))) == 1


@pytest.mark.parametrize(
    "environment, expected_message",
    [
        ({}, "BEDSY_AI_PRODUCTION_BOOTSTRAP_ENABLED"),
        ({BOOTSTRAP_ENABLED: "true"}, "APP_ENV must be production"),
        ({BOOTSTRAP_ENABLED: "true", APP_ENV: "production"}, "DATABASE_URL must be"),
        (
            {BOOTSTRAP_ENABLED: "true", APP_ENV: "production", DATABASE_URL: "sqlite:////tmp/bedsynth.db"},
            "DATABASE_URL must be",
        ),
        (
            {BOOTSTRAP_ENABLED: "true", APP_ENV: "production", DATABASE_URL: "sqlite:////data/bedsynth.db"},
            "FRONTEND_ORIGINS must contain",
        ),
    ],
)
def test_missing_or_invalid_bootstrap_environment_is_refused(environment, expected_message) -> None:
    with pytest.raises(BootstrapRefused, match=expected_message):
        validate_bootstrap_environment(environment)


def test_valid_production_environment_requires_exact_https_origin() -> None:
    config = validate_bootstrap_environment(
        {
            BOOTSTRAP_ENABLED: "true",
            APP_ENV: "production",
            DATABASE_URL: "sqlite:////data/bedsynth.db",
            FRONTEND_ORIGINS: "https://bedsynth.example.test",
        }
    )
    assert config.database_url == "sqlite:////data/bedsynth.db"

    with pytest.raises(BootstrapRefused, match="exact HTTPS origins"):
        validate_bootstrap_environment(
            {
                BOOTSTRAP_ENABLED: "true",
                APP_ENV: "production",
                DATABASE_URL: "sqlite:////data/bedsynth.db",
                FRONTEND_ORIGINS: "*",
            }
        )


@pytest.mark.parametrize(
    "email,password",
    [
        (None, "long-safe-test-password"),
        ("bad-email", "long-safe-test-password"),
        ("admin@example.test", None),
        ("admin@example.test", "short"),
        ("admin@example.test", "x" * 129),
    ],
)
def test_missing_or_invalid_credentials_are_refused(email, password) -> None:
    with pytest.raises(BootstrapRefused):
        validate_admin_credentials(email, password)


def test_seed_failure_rolls_back_admin_demo_configuration_and_marker(bootstrap_db: Session) -> None:
    def fail_after_write(db: Session) -> None:
        db.add(Workspace(name="Partial seed workspace"))
        db.flush()
        raise RuntimeError("sensitive details must not escape")

    with pytest.raises(RuntimeError):
        bootstrap_database(
            bootstrap_db,
            "admin@example.test",
            "long-safe-test-password",
            seed_function=fail_after_write,
        )

    assert _counts(bootstrap_db) == (0, 0, 0, 0)
    assert bootstrap_db.scalar(select(func.count(Workspace.id))) == 0
    assert bootstrap_db.get(ProductionBootstrapRecord, 1) is None


def test_fresh_database_preflight_initializes_schema_and_existing_data_skips_callback(
    bootstrap_engine, monkeypatch,
) -> None:
    monkeypatch.setattr(database, "engine", bootstrap_engine)
    assert prepare_database_for_bootstrap(bootstrap_engine, database.initialize_database) is True
    assert "production_bootstrap_records" in inspect(bootstrap_engine).get_table_names()

    with bootstrap_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE existing_data (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO existing_data (id) VALUES (1)")
    called = False

    def should_not_initialize() -> None:
        nonlocal called
        called = True

    with pytest.raises(BootstrapRefused, match="existing application data"):
        prepare_database_for_bootstrap(bootstrap_engine, should_not_initialize)
    assert called is False


def test_cli_failure_does_not_print_exception_details(monkeypatch, capsys) -> None:
    monkeypatch.setattr(bootstrap_module, "load_backend_environment", lambda: None)

    def fail_without_logging() -> bool:
        raise RuntimeError("secret-value-must-not-be-printed")

    monkeypatch.setattr(bootstrap_module, "run_bootstrap", fail_without_logging)
    assert bootstrap_module.main() == 1
    captured = capsys.readouterr()
    assert "secret-value-must-not-be-printed" not in captured.out + captured.err
    assert "failed safely" in captured.err


def test_environment_variable_names_are_documented_without_values() -> None:
    assert BOOTSTRAP_ADMIN_EMAIL == "BEDSY_AI_BOOTSTRAP_ADMIN_EMAIL"
    assert BOOTSTRAP_ADMIN_PASSWORD == "BEDSY_AI_BOOTSTRAP_ADMIN_PASSWORD"
    assert DATABASE_URL == "DATABASE_URL"
