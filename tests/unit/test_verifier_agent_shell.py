"""Contract tests for the Verifier Agent service shell."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import cast

from httpx import ASGITransport, AsyncClient

from agents.verifier.agent_card import create_agent_card
from agents.verifier.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_agent_card_advertises_fact_verification_and_json_modes() -> None:
    card = create_agent_card("http://verifier.test/")

    assert card.name == "AgentDesk Verifier Agent"
    assert card.supported_interfaces[0].url == "http://verifier.test"
    assert card.capabilities.streaming is True
    assert card.default_input_modes == ["application/json"]
    assert card.default_output_modes == ["application/json"]
    assert [skill.id for skill in card.skills] == ["fact-verification"]


def test_operations_endpoints_are_outside_the_a2a_surface() -> None:
    async def request_operations() -> tuple[tuple[int, dict[str, str]], tuple[int, dict[str, str]]]:
        transport = ASGITransport(app=create_app("http://verifier.test"))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            ready = await client.get("/ready")
        return (health.status_code, health.json()), (ready.status_code, ready.json())

    health, ready = asyncio.run(request_operations())

    assert health == (200, {"service": "verifier-agent", "status": "ok"})
    assert ready == (200, {"service": "verifier-agent", "status": "ready"})


def test_agent_card_is_discoverable_from_the_standalone_app() -> None:
    async def request_card() -> tuple[int, dict[str, object]]:
        transport = ASGITransport(app=create_app("http://verifier.test"))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/.well-known/agent-card.json")
        return response.status_code, response.json()

    status_code, card = asyncio.run(request_card())
    skills = cast(list[dict[str, object]], card["skills"])

    assert status_code == 200
    assert card["name"] == "AgentDesk Verifier Agent"
    assert [skill["id"] for skill in skills] == ["fact-verification"]


def test_verifier_agent_does_not_import_coordinator_implementation() -> None:
    verifier_root = ROOT / "agents" / "verifier"
    imported_modules: set[str] = set()

    for source_path in verifier_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

    assert not any(module.startswith("agents.coordinator") for module in imported_modules)
