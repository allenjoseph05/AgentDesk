"""Compose contract checks that fixture demo mode is explicit and deterministic."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _compose_config(*files: str) -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required to resolve the demo stack contract.")
    command = ["docker", "compose"]
    for file in files:
        command.extend(("--file", file))
    command.extend(("config", "--format", "json"))
    result = subprocess.run(
        command,
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


def test_default_stack_remains_live_and_uses_production_entry_points() -> None:
    services = _compose_config("compose.yaml")["services"]

    assert services["web"]["environment"]["VITE_AGENTDESK_RUNTIME_MODE"] == "live"
    for service, module in {
        "researcher": "agents.researcher.main:app",
        "analyst": "agents.analyst.main:app",
        "verifier": "agents.verifier.main:app",
        "coordinator": "agents.coordinator.main:app",
    }.items():
        assert module in services[service]["command"]


def test_demo_override_selects_fixture_apps_and_fixed_stage_delays() -> None:
    services = _compose_config("compose.yaml", "compose.demo.yaml")["services"]

    assert services["web"]["environment"]["VITE_AGENTDESK_RUNTIME_MODE"] == "demo"
    assert "agents.researcher.fixture_app:app" in services["researcher"]["command"]
    assert "agents.analyst.fixture_app:app" in services["analyst"]["command"]
    assert "agents.verifier.fixture_app:app" in services["verifier"]["command"]
    assert "agents.coordinator.fixture_app:app" in services["coordinator"]["command"]

    assert services["researcher"]["environment"]["RESEARCH_FIXTURE_SEARCH_DELAY_SECONDS"] == "0.75"
    assert services["analyst"]["environment"]["ANALYST_FIXTURE_DELAY_SECONDS"] == "0.75"
    assert services["verifier"]["environment"]["VERIFIER_FIXTURE_DELAY_SECONDS"] == "0.5"
    assert services["coordinator"]["environment"]["AGENTDESK_DEMO_PLANNING_DELAY_SECONDS"] == "0.35"
    assert services["coordinator"]["environment"]["OPENAI_API_KEY"] == ""
    assert "sleep" not in json.dumps(services).casefold()
