"""Contract checks for the health-gated Docker Compose developer stack."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "compose.yaml"
REQUIRED_SERVICES = {
    "web",
    "coordinator",
    "researcher",
    "analyst",
    "verifier",
    "postgres",
}


def _resolved_compose_config() -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required to resolve the developer stack contract.")
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(f"docker compose config failed:\n{result.stderr}")
    config = json.loads(result.stdout)
    assert isinstance(config, dict)
    return config


def test_default_compose_entrypoint_defines_every_runtime_service() -> None:
    assert COMPOSE_FILE.is_file()
    config = _resolved_compose_config()
    services = config["services"]

    assert REQUIRED_SERVICES <= services.keys()
    assert "migrate" in services
    assert services["postgres"]["image"] == "postgres:17.6-alpine"
    for service_name in REQUIRED_SERVICES - {"postgres"}:
        assert "build" in services[service_name]


def test_compose_startup_uses_health_and_completion_conditions_without_sleeps() -> None:
    config = _resolved_compose_config()
    services = config["services"]

    for service_name in REQUIRED_SERVICES:
        assert "healthcheck" in services[service_name]

    assert services["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    coordinator_dependencies = services["coordinator"]["depends_on"]
    assert coordinator_dependencies["migrate"]["condition"] == "service_completed_successfully"
    for specialist in ("researcher", "analyst", "verifier"):
        assert coordinator_dependencies[specialist]["condition"] == "service_healthy"
    assert services["web"]["depends_on"]["coordinator"]["condition"] == "service_healthy"
    assert "sleep" not in json.dumps(config).casefold()
