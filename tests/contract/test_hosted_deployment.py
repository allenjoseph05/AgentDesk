"""On-demand Codespaces and optional Render deployment contract checks for AD-112."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT = ROOT / "render.yaml"
DEVCONTAINER = ROOT / ".devcontainer" / "devcontainer.json"
CODESPACES_COMPOSE = ROOT / "compose.codespaces.yaml"
CODESPACES_SCRIPT = ROOT / "scripts" / "codespaces_demo.sh"


def _blueprint() -> dict[str, Any]:
    loaded = yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _services() -> dict[str, dict[str, Any]]:
    services = _blueprint()["services"]
    return {service["name"]: service for service in services}


def _environment(service: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["key"]: entry for entry in service.get("envVars", [])}


def test_blueprint_exposes_only_the_tls_ingress_service() -> None:
    services = _services()

    assert set(services) == {
        "agentdesk-researcher",
        "agentdesk-analyst",
        "agentdesk-verifier",
        "agentdesk-coordinator",
        "agentdesk-demo",
    }
    assert services["agentdesk-demo"]["type"] == "web"
    assert services["agentdesk-demo"]["renderSubdomainPolicy"] == "enabled"
    assert all(
        service["type"] == "pserv" for name, service in services.items() if name != "agentdesk-demo"
    )
    for service in services.values():
        assert service["runtime"] == "docker"
        assert service["plan"] == "starter"
        assert service["region"] == "frankfurt"
        assert service["autoDeployTrigger"] == "checksPass"
    assert services["agentdesk-demo"]["healthCheckPath"] == "/healthz"
    assert all(
        "healthCheckPath" not in service
        for name, service in services.items()
        if name != "agentdesk-demo"
    )


def test_blueprint_uses_fixture_agents_and_private_property_references() -> None:
    services = _services()
    expected_modules = {
        "agentdesk-researcher": "agents.researcher.fixture_app:app",
        "agentdesk-analyst": "agents.analyst.fixture_app:app",
        "agentdesk-verifier": "agents.verifier.fixture_app:app",
    }
    for name, module in expected_modules.items():
        assert module in services[name]["dockerCommand"]
        assert services[name]["type"] == "pserv"

    coordinator = services["agentdesk-coordinator"]
    assert coordinator["dockerCommand"] == "python scripts/start_hosted_coordinator.py"
    assert coordinator["preDeployCommand"] == "python -m alembic upgrade head"
    coordinator_env = _environment(coordinator)
    assert coordinator_env["DATABASE_URL"]["fromDatabase"] == {
        "name": "agentdesk-postgres",
        "property": "connectionString",
    }
    for key, name in {
        "RESEARCH_AGENT_HOSTPORT": "agentdesk-researcher",
        "ANALYST_AGENT_HOSTPORT": "agentdesk-analyst",
        "VERIFIER_AGENT_HOSTPORT": "agentdesk-verifier",
    }.items():
        assert coordinator_env[key]["fromService"] == {
            "type": "pserv",
            "name": name,
            "property": "hostport",
        }


def test_blueprint_keeps_database_private_and_contains_no_live_secret() -> None:
    blueprint = _blueprint()
    assert blueprint["databases"] == [
        {
            "name": "agentdesk-postgres",
            "plan": "basic-256mb",
            "region": "frankfurt",
            "postgresMajorVersion": "17",
            "databaseName": "agentdesk",
            "user": "agentdesk",
            "ipAllowList": [],
        }
    ]
    serialized = BLUEPRINT.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in serialized
    assert "AGENTDESK_BROWSER_TOKEN" not in serialized
    assert "AGENTDESK_SERVICE_TOKEN" not in serialized
    assert "sync: false" not in serialized


def test_hosted_web_uses_a_production_build_and_private_proxy_target() -> None:
    service = _services()["agentdesk-demo"]
    environment = _environment(service)

    assert service["dockerfilePath"] == "./apps/web/Dockerfile.production"
    assert environment["VITE_AGENTDESK_RUNTIME_MODE"]["value"] == "demo"
    assert environment["VITE_AGENTDESK_AG_UI_ENDPOINT"]["value"] == "/ag-ui"
    assert environment["AGENTDESK_COORDINATOR_HOSTPORT"]["fromService"] == {
        "type": "pserv",
        "name": "agentdesk-coordinator",
        "property": "hostport",
    }

    dockerfile = (ROOT / "apps" / "web" / "Dockerfile.production").read_text(encoding="utf-8")
    assert "npm run build --workspace @agentdesk/web" in dockerfile
    assert 'CMD ["node", "production-server.mjs"]' in dockerfile
    assert "npm run dev" not in dockerfile


def test_codespaces_devcontainer_installs_docker_and_forwards_only_the_web_port() -> None:
    configuration = json.loads(DEVCONTAINER.read_text(encoding="utf-8"))

    assert configuration["image"] == "mcr.microsoft.com/devcontainers/base:ubuntu-24.04"
    assert configuration["features"] == {
        "ghcr.io/devcontainers/features/docker-in-docker:2": {},
        "ghcr.io/devcontainers/features/sshd:1": {"version": "latest"},
    }
    assert configuration["forwardPorts"] == [5173]
    assert configuration["portsAttributes"] == {
        "5173": {
            "label": "AgentDesk fixture demo",
            "onAutoForward": "notify",
            "protocol": "http",
        }
    }
    assert "visibility" not in configuration["portsAttributes"]["5173"]
    assert configuration["hostRequirements"] == {
        "cpus": 2,
        "memory": "8gb",
        "storage": "32gb",
    }


def test_codespaces_compose_uses_production_ingress_and_hides_python_ports() -> None:
    compose = CODESPACES_COMPOSE.read_text(encoding="utf-8")

    assert compose.count("ports: !override []") == 4
    assert "dockerfile: apps/web/Dockerfile.production" in compose
    assert "VITE_AGENTDESK_RUNTIME_MODE: demo" in compose
    assert "AGENTDESK_COORDINATOR_URL: http://coordinator:8000" in compose
    assert 'PORT: "5173"' in compose
    assert '"127.0.0.1:5173:5173"' in compose
    assert "http://127.0.0.1:5173/healthz" in compose


def test_codespaces_script_validates_starts_and_stops_the_exact_profile() -> None:
    script = CODESPACES_SCRIPT.read_text(encoding="utf-8")

    assert "set -euo pipefail" in script
    assert "-f compose.yaml" in script
    assert "-f compose.demo.yaml" in script
    assert "-f compose.codespaces.yaml" in script
    assert "compose config --quiet" in script
    assert "compose up --build --wait" in script
    assert "compose down" in script
    assert "--volumes" not in script
    assert "Port Visibility" not in script
    assert "set port 5173 visibility to Public" in script


def test_deployment_runbook_makes_codespaces_default_and_render_optional() -> None:
    deployment = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")

    assert "# Zero-cost on-demand hosted demo" in deployment
    assert "bash scripts/codespaces_demo.sh up" in deployment
    assert "Port Visibility** -> **Public" in deployment
    assert "Only port `5173` is public" in deployment
    assert "public port must be made public again" in deployment
    assert "Optional paid Render reference" in deployment
    assert "must never be deployed without separate explicit" in deployment
