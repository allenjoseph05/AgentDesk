"""Repository contracts for the adaptive-intake compatibility spike."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCOPER = ROOT / "services" / "scoper"
A2UI_PYTHON = ROOT / "spikes" / "a2ui-python"
A2UI_WEB = ROOT / "spikes" / "a2ui-web"


def test_scoper_dependencies_are_exact_and_isolated_from_root() -> None:
    scoper_project = (SCOPER / "pyproject.toml").read_text(encoding="utf-8")
    scoper_lock = (SCOPER / "requirements.lock").read_text(encoding="utf-8")
    root_project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    root_lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")

    assert '"google-adk[a2a]==2.7.1"' in scoper_project
    assert '"a2a-sdk[fastapi]==1.1.2"' in scoper_project
    assert "google-adk==2.7.1" in scoper_lock
    assert "opentelemetry-sdk==1.42.1" in scoper_lock
    assert "google-adk" not in root_project
    assert "google-adk" not in root_lock
    assert "opentelemetry-sdk==1.44.0" in root_lock


def test_a2ui_compatibility_graphs_are_exact_and_not_runtime_dependencies() -> None:
    python_project = (A2UI_PYTHON / "pyproject.toml").read_text(encoding="utf-8")
    python_lock = (A2UI_PYTHON / "requirements.lock").read_text(encoding="utf-8")
    web_package = json.loads((A2UI_WEB / "package.json").read_text(encoding="utf-8"))
    production_web = json.loads(
        (ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8")
    )

    assert '"a2ui-core==0.1.1"' in python_project
    assert "a2ui-core==0.1.1" in python_lock
    assert "opentelemetry-sdk==1.44.0" in python_lock
    assert web_package["dependencies"]["@a2ui/react"] == "0.10.2"
    assert web_package["dependencies"]["@a2ui/web_core"] == "0.10.6"
    assert web_package["overrides"] == {"dompurify": "3.4.13"}
    assert "@a2ui/react" not in production_web["dependencies"]
    assert "@a2ui/web_core" not in production_web["dependencies"]


def test_compatibility_job_resolves_and_tests_each_environment() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    job = workflow["jobs"]["adaptive-intake-compatibility"]
    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])

    assert job["timeout-minutes"] == 10
    assert "services/scoper/requirements.lock" in commands
    assert "services/scoper/tests" in commands
    assert "spikes/a2ui-python/requirements.lock" in commands
    assert "spikes/a2ui-python/tests" in commands
    assert "npm ci --ignore-scripts --prefix spikes/a2ui-web" in commands
    assert "npm audit --audit-level=low --prefix spikes/a2ui-web" in commands


def test_compatibility_decision_selects_adapter_without_a_runtime_route() -> None:
    decision = (ROOT / "docs" / "adaptive-intake-compatibility.md").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "AgentDesk A2A adapter selected" in decision
    assert "Do not use ADK 2.7.1's experimental native" in decision
    assert "zero model calls and zero credentials" in decision
    assert "Product/runtime changes: none" in decision
    assert "scoper:" not in compose
