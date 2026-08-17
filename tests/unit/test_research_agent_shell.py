"""Contract tests for the Research Agent service shell."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from agents.researcher.agent_card import create_agent_card
from agents.researcher.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_agent_card_advertises_research_skills_and_json_modes() -> None:
    card = create_agent_card("http://research.test/")

    assert card.name == "AgentDesk Research Agent"
    assert card.supported_interfaces[0].url == "http://research.test"
    assert card.capabilities.streaming is True
    assert card.default_input_modes == ["application/json"]
    assert card.default_output_modes == ["application/json"]
    assert {skill.id for skill in card.skills} == {"web-research", "source-synthesis"}


def test_operations_endpoints_are_outside_the_a2a_surface() -> None:
    async def request_operations() -> tuple[tuple[int, dict[str, str]], tuple[int, dict[str, str]]]:
        transport = ASGITransport(app=create_app("http://research.test"))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            ready = await client.get("/ready")
        return (health.status_code, health.json()), (ready.status_code, ready.json())

    health, ready = asyncio.run(request_operations())

    assert health == (200, {"service": "research-agent", "status": "ok"})
    assert ready == (200, {"service": "research-agent", "status": "ready"})


def test_agent_card_is_discoverable_from_the_standalone_app() -> None:
    async def request_card() -> tuple[int, dict[str, object]]:
        transport = ASGITransport(app=create_app("http://research.test"))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/.well-known/agent-card.json")
        return response.status_code, response.json()

    status_code, card = asyncio.run(request_card())

    assert status_code == 200
    assert card["name"] == "AgentDesk Research Agent"
    assert {skill["id"] for skill in card["skills"]} == {
        "web-research",
        "source-synthesis",
    }


def test_research_agent_does_not_import_coordinator_implementation() -> None:
    researcher_root = ROOT / "agents" / "researcher"
    imported_modules: set[str] = set()

    for source_path in researcher_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

    assert not any(module.startswith("agents.coordinator") for module in imported_modules)
