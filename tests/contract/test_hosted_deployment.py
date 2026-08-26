"""Render Blueprint and hosted-runtime contract checks for AD-112."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT = ROOT / "render.yaml"


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
