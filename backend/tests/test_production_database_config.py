import pytest

from app.database import configured_database_url


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
