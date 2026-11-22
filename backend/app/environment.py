"""Load backend environment variables from the backend directory."""

from pathlib import Path

from dotenv import load_dotenv

BACKEND_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_backend_environment(env_file: Path = BACKEND_ENV_FILE) -> None:
    """Load backend/.env independent of the process working directory.

    Existing process environment variables take precedence over values in the
    local file. The file contents are never logged or returned.
    """
    load_dotenv(dotenv_path=env_file, override=False)
