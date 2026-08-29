"""Deployment and observability contracts for the final adaptive-intake rollout story."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "infrastructure" / "observability" / "adaptive-intake-dashboard.json"
SCOPER_DOCKERFILE = ROOT / "services" / "scoper" / "Dockerfile"


def _adaptive_compose() -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required to resolve the adaptive rollout contract.")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            "compose.yaml",
            "--file",
            "compose.demo.yaml",
            "--file",
            "compose.adaptive.yaml",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(f"docker compose config failed:\n{result.stderr}")
    loaded = json.loads(result.stdout)
    assert isinstance(loaded, dict)
    return loaded


def test_scoper_image_is_isolated_non_root_and_uses_its_exact_lock() -> None:
    dockerfile = SCOPER_DOCKERFILE.read_text(encoding="utf-8")

    assert "services/scoper/requirements.lock" in dockerfile
    assert "pip install --no-cache-dir -r services/scoper/requirements.lock" in dockerfile
    assert "requirements.lock pyproject.toml" not in dockerfile
    assert "SCOPER_FIXTURE_DIRECTORY=/app/fixtures/intake" in dockerfile
    assert "USER scoper" in dockerfile
    assert "EXPOSE 8011" in dockerfile
    assert "agentdesk_scoper.main:app" in dockerfile


def test_adaptive_compose_overlay_is_explicit_key_free_and_health_gated() -> None:
    services = _adaptive_compose()["services"]

    assert services["scoper"]["environment"]["SCOPER_MODE"] == "fixture"
    assert "GOOGLE_API_KEY" not in services["scoper"]["environment"]
    assert services["coordinator"]["environment"]["AGENTDESK_ADAPTIVE_SCOPING_ENABLED"] == "true"
    assert services["coordinator"]["environment"]["SCOPER_AGENT_URL"] == "http://scoper:8011"
    assert services["coordinator"]["depends_on"]["scoper"]["condition"] == "service_healthy"
    assert services["web"]["environment"]["VITE_AGENTDESK_ADAPTIVE_INTAKE_ENABLED"] == "true"
    assert services["web"]["environment"]["VITE_AGENTDESK_RUNTIME_MODE"] == "adaptive-demo"


def test_dashboard_covers_every_rollout_signal_without_user_content() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    panels = {panel["id"]: panel for panel in dashboard["panels"]}

    assert set(panels) == {
        "proposal-validity",
        "intake-decisions",
        "fallback-rate",
        "scoper-latency",
        "scoper-token-use",
        "downstream-quality",
    }
    assert dashboard["contentPolicy"]["allowUserContent"] is False
    assert dashboard["rolloutStages"][-1]["blockedUntilDecision"] == "eligible"
    assert panels["scoper-latency"]["measure"] == "duration_ms"
    assert panels["scoper-token-use"]["measure"] == ["input_tokens", "output_tokens"]
    assert panels["downstream-quality"]["path"] == "fixtures/intake/fixture-evaluation.json"

    queries = "\n".join(panel.get("query", "") for panel in panels.values()).casefold()
    for prohibited in dashboard["contentPolicy"]["prohibitedFields"]:
        assert prohibited.casefold() not in queries
