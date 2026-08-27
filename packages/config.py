"""Shared loading for the repository-local development environment."""

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project_environment() -> None:
    """Load `.env` without overriding explicitly supplied process variables."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def service_url_from_environment(
    url_name: str,
    hostport_name: str,
    default: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve a full URL or a platform-provided private host/port reference."""
    source = os.environ if environ is None else environ
    explicit_url = source.get(url_name, "").strip()
    if explicit_url:
        return explicit_url
    hostport = source.get(hostport_name, "").strip()
    if hostport:
        if "://" in hostport or any(character.isspace() for character in hostport):
            raise ValueError(f"{hostport_name} must contain only a private host and port.")
        return f"http://{hostport}"
    return default
