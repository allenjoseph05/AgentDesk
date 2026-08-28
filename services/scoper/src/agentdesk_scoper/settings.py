"""Validated runtime settings for the isolated scoper service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ScoperMode = Literal["fixture", "live"]


def repository_root() -> Path:
    """Locate the repository without relying on the process working directory."""
    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class ScoperSettings:
    """Small, explicit configuration surface for one scoper process."""

    mode: ScoperMode = "fixture"
    base_url: str = "http://127.0.0.1:8011"
    fixture_id: str = "technology-database"
    fixture_directory: Path = repository_root() / "fixtures" / "intake"
    timeout_seconds: float = 10.0
    max_attempts: int = 1
    retry_delay_seconds: float = 0.1
    model_name: str | None = None
    provider_configured: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"fixture", "live"}:
            raise ValueError("SCOPER_MODE must be fixture or live.")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("SCOPER_BASE_URL must be an HTTP URL.")
        if not self.fixture_id.strip():
            raise ValueError("SCOPER_FIXTURE_ID cannot be blank.")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 120:
            raise ValueError("SCOPER_TIMEOUT_SECONDS must be between 0 and 120.")
        if self.max_attempts not in {1, 2}:
            raise ValueError("SCOPER_MAX_ATTEMPTS must be 1 or 2.")
        if self.retry_delay_seconds < 0 or self.retry_delay_seconds > 5:
            raise ValueError("SCOPER_RETRY_DELAY_SECONDS must be between 0 and 5.")

    @property
    def ready(self) -> bool:
        if self.mode == "fixture":
            return (self.fixture_directory / f"{self.fixture_id}.golden.json").is_file()
        return bool(self.model_name and self.provider_configured)

    @property
    def readiness_reason(self) -> str:
        if self.ready:
            return "ready"
        if self.mode == "fixture":
            return "fixture_not_found"
        return "live_provider_not_configured"

    @classmethod
    def from_environment(cls) -> ScoperSettings:
        mode = os.getenv("SCOPER_MODE", "fixture").strip().casefold()
        if mode not in {"fixture", "live"}:
            raise ValueError("SCOPER_MODE must be fixture or live.")

        # Fixture mode deliberately does not inspect provider credentials.
        model_name: str | None = None
        provider_configured = False
        if mode == "live":
            model_name = os.getenv("SCOPER_MODEL") or None
            provider_configured = bool(os.getenv("GOOGLE_API_KEY"))

        fixture_directory = Path(
            os.getenv(
                "SCOPER_FIXTURE_DIRECTORY",
                str(repository_root() / "fixtures" / "intake"),
            )
        )
        return cls(
            mode=mode,
            base_url=os.getenv("SCOPER_BASE_URL", "http://127.0.0.1:8011").rstrip("/"),
            fixture_id=os.getenv("SCOPER_FIXTURE_ID", "technology-database"),
            fixture_directory=fixture_directory,
            timeout_seconds=float(os.getenv("SCOPER_TIMEOUT_SECONDS", "10")),
            max_attempts=int(os.getenv("SCOPER_MAX_ATTEMPTS", "1")),
            retry_delay_seconds=float(os.getenv("SCOPER_RETRY_DELAY_SECONDS", "0.1")),
            model_name=model_name,
            provider_configured=provider_configured,
        )
