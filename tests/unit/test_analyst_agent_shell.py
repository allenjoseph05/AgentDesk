"""Contract tests for the Analyst Agent service shell."""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import Event, EventQueue
from a2a.types import Message, Role, SendMessageRequest
from httpx import ASGITransport, AsyncClient

from agents.analyst.agent_card import create_agent_card
from agents.analyst.executor import AnalystAgentExecutor
from agents.analyst.main import create_app
from packages.contracts import AnalysisRequest, Claim, Evidence, EvidenceBundle

ROOT = Path(__file__).resolve().parents[2]


class RecordingEventQueue(EventQueue):
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def enqueue_event(self, event: Event) -> None:
        self.events.append(event)


def _analysis_request() -> AnalysisRequest:
    evidence = Evidence(
        id="evidence-1",
        title="PostgreSQL documentation",
        source_url="https://www.postgresql.org/docs/current/",
        source_type="official_documentation",
        summary="PostgreSQL supports relational constraints.",
        relevance=0.95,
        retrieved_at=datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
    )
    return AnalysisRequest(
        question="Should this workload use PostgreSQL or MongoDB?",
        options=["PostgreSQL", "MongoDB"],
        constraints=["Preserve relational integrity"],
        criteria=["Data integrity", "Operational complexity"],
        evidence_bundle=EvidenceBundle(
            question="Should this workload use PostgreSQL or MongoDB?",
            claims=[
                Claim(
                    id="claim-1",
                    statement="PostgreSQL supports relational integrity constraints.",
                    evidence_ids=["evidence-1"],
                    confidence=0.9,
                )
            ],
            evidence=[evidence],
            unknowns=["Production query distribution is not measured."],
        ),
    )


def _context(payload: str) -> RequestContext:
    return RequestContext(
        ServerCallContext(),
        request=SendMessageRequest(
            message=new_text_message(payload, media_type="application/json", role=Role.ROLE_USER)
        ),
        task_id="analyst-task-1",
        context_id="analyst-context-1",
    )


def test_agent_card_advertises_decision_analysis_and_json_modes() -> None:
    card = create_agent_card("http://analyst.test/")

    assert card.name == "AgentDesk Analyst Agent"
    assert card.supported_interfaces[0].url == "http://analyst.test"
    assert card.capabilities.streaming is True
    assert card.default_input_modes == ["application/json"]
    assert card.default_output_modes == ["application/json"]
    assert [skill.id for skill in card.skills] == ["decision-analysis"]


def test_service_accepts_a_structured_evidence_request() -> None:
    queue = RecordingEventQueue()

    asyncio.run(
        AnalystAgentExecutor().execute(_context(_analysis_request().model_dump_json()), queue)
    )

    assert len(queue.events) == 1
    response = queue.events[0]
    assert isinstance(response, Message)
    assert get_message_text(response) == (
        "Structured evidence accepted; analysis is not configured yet."
    )


def test_service_rejects_malformed_evidence_input_at_the_contract_boundary() -> None:
    queue = RecordingEventQueue()

    asyncio.run(
        AnalystAgentExecutor().execute(
            _context('{"question":"Compare databases","evidence_bundle":{}}'), queue
        )
    )

    assert len(queue.events) == 1
    response = queue.events[0]
    assert isinstance(response, Message)
    assert "AnalysisRequest schema" in get_message_text(response)


def test_operations_endpoints_and_agent_card_are_available() -> None:
    async def request_endpoints() -> tuple[dict[str, str], dict[str, str], dict[str, object]]:
        transport = ASGITransport(app=create_app("http://analyst.test"))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            ready = await client.get("/ready")
            card = await client.get("/.well-known/agent-card.json")
        assert health.status_code == ready.status_code == card.status_code == 200
        return health.json(), ready.json(), card.json()

    health, ready, card = asyncio.run(request_endpoints())

    assert health == {"service": "analyst-agent", "status": "ok"}
    assert ready == {"service": "analyst-agent", "status": "ready"}
    assert card["name"] == "AgentDesk Analyst Agent"
    assert [skill["id"] for skill in card["skills"]] == ["decision-analysis"]


def test_analyst_agent_does_not_import_other_agent_implementations() -> None:
    analyst_root = ROOT / "agents" / "analyst"
    imported_modules: set[str] = set()

    for source_path in analyst_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

    assert not any(
        module.startswith(("agents.coordinator", "agents.researcher", "agents.verifier"))
        for module in imported_modules
    )
