"""Shared loading for the repository-local development environment."""

from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project_environment() -> None:
    """Load `.env` without overriding explicitly supplied process variables."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
