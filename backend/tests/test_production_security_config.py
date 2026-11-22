import pytest

from app.auth import configured_frontend_origins


def test_production_requires_explicit_frontend_origin() -> None:
    with pytest.raises(RuntimeError, match="FRONTEND_ORIGINS must explicitly allow"):
        configured_frontend_origins("production", None, None)


def test_production_accepts_exact_https_frontend_origins() -> None:
    assert configured_frontend_origins(
        "production", "https://bedsynth.example, https://preview.example", None
    ) == ("https://bedsynth.example", "https://preview.example")


@pytest.mark.parametrize("origins", ["*", "http://bedsynth.example", "https://bedsynth.example/path"])
def test_production_rejects_non_exact_or_insecure_origins(origins: str) -> None:
    with pytest.raises(RuntimeError, match="exact HTTPS origins"):
        configured_frontend_origins("production", origins, None)


def test_development_keeps_local_origin_default() -> None:
    assert configured_frontend_origins("development", None, None) == ("http://localhost:3000",)
