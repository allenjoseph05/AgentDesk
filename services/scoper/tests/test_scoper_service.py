"""Production service and free-mode tests for the isolated ADK scoper."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import new_text_message
from a2a.types import Role, SendMessageRequest, TaskState
from a2a.utils.constants import TransportProtocol
from google.adk.agents.invocation_context import InvocationContext
from google.adk.evaluation.eval_set import EvalSet
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.protobuf.json_format import MessageToDict
from packages.contracts import ScopeProposal, ScopeProposalArtifact, ScopingRequest
from pydantic import ValidationError

from agentdesk_scoper.executor import ScoperAgentExecutor
from agentdesk_scoper.fixture_agent import FixtureScoperAgent
from agentdesk_scoper.fixture_library import load_fixture_proposal
from agentdesk_scoper.live_agent import create_live_agent
from agentdesk_scoper.main import create_app, create_runtime_agent
from agentdesk_scoper.settings import ScoperSettings

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class _Context:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.task_id = "task-123"
        self.context_id = "context-123"
        self.message = new_text_message(
            json.dumps(payload),
            media_type="application/json",
            role=Role.ROLE_USER,
        )

    def get_user_input(self) -> str:
        return self.message.parts[0].text


class _Queue:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


class _FlakyFixtureAgent(FixtureScoperAgent):
    attempts: int = 0

    async def _run_async_impl(self, ctx: InvocationContext) -> Any:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("synthetic transient failure")
        async for event in super()._run_async_impl(ctx):
            yield event


async def _a2a_events(app: Any, payload: dict[str, Any]) -> list[Any]:
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://scoper.test")
    async with app.router.lifespan_context(app):
        client = await ClientFactory(
            ClientConfig(
                streaming=True,
                httpx_client=http_client,
                supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
            )
        ).create_from_url("http://scoper.test")
        try:
            request = SendMessageRequest(
                message=new_text_message(
                    json.dumps(payload),
                    media_type="application/json",
                    role=Role.ROLE_USER,
                )
            )
            return [event async for event in client.send_message(request)]
        finally:
            await client.close()
            if not http_client.is_closed:
                await http_client.aclose()


def _settings(**overrides: Any) -> ScoperSettings:
    values = {
        "fixture_directory": REPOSITORY_ROOT / "fixtures" / "intake",
        "base_url": "http://scoper.test",
    }
    values.update(overrides)
    return ScoperSettings(**values)


def test_fixture_mode_does_not_read_provider_credentials(monkeypatch: Any) -> None:
    original_getenv = __import__("os").getenv

    def guarded_getenv(name: str, default: str | None = None) -> str | None:
        if name == "GOOGLE_API_KEY":
            raise AssertionError("fixture mode inspected a provider credential")
        return original_getenv(name, default)

    monkeypatch.setattr("agentdesk_scoper.settings.os.getenv", guarded_getenv)
    settings = ScoperSettings.from_environment()
    agent = create_runtime_agent(settings)

    assert settings.mode == "fixture"
    assert settings.ready
    assert isinstance(agent, FixtureScoperAgent)


def test_live_mode_is_opt_in_and_structured(monkeypatch: Any) -> None:
    monkeypatch.setenv("SCOPER_MODE", "live")
    monkeypatch.delenv("SCOPER_MODEL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    unavailable = ScoperSettings.from_environment()

    assert not unavailable.ready
    assert unavailable.readiness_reason == "live_provider_not_configured"

    agent = create_live_agent("gemini-test-model")
    assert agent.output_schema is ScopeProposal
    assert agent.tools == []
    assert agent.mode == "single_turn"


def test_health_readiness_and_agent_card() -> None:
    app = create_app(_settings())

    async def read() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://scoper.test",
            ) as client:
                return (
                    await client.get("/health"),
                    await client.get("/ready"),
                    await client.get("/.well-known/agent-card.json"),
                )

    health, ready, card = asyncio.run(read())
    assert health.json() == {"service": "decision-scoper", "status": "ok", "mode": "fixture"}
    assert ready.status_code == 200
    assert ready.json()["reason"] == "ready"
    assert card.json()["skills"][0]["id"] == "decision-scoping"
    assert card.json()["supportedInterfaces"][0]["protocolBinding"] == "HTTP+JSON"


def test_production_a2a_stream_returns_valid_envelope() -> None:
    question = "Should we choose PostgreSQL or MongoDB?"
    events = asyncio.run(_a2a_events(create_app(_settings()), {"question": question}))
    artifact_event = next(
        event for event in events if event.WhichOneof("payload") == "artifact_update"
    )
    artifact = artifact_event.artifact_update.artifact
    envelope = ScopeProposalArtifact.model_validate(MessageToDict(artifact.parts[0].data))

    assert artifact.name == "scope-proposal"
    assert envelope.provenance.producer_agent == "decision-scoper"
    assert envelope.provenance.remote_task_id == artifact_event.artifact_update.task_id
    assert envelope.payload.question == question
    assert events[-1].status_update.status.state == TaskState.TASK_STATE_COMPLETED


def test_invalid_request_output_and_timeout_fail_without_artifact() -> None:
    invalid_events = asyncio.run(_a2a_events(create_app(_settings()), {"question": ""}))
    malformed_events = asyncio.run(
        _a2a_events(
            create_app(
                _settings(),
                agent=FixtureScoperAgent(
                    name="malformed_scoper",
                    description="Returns invalid output deterministically.",
                    malformed_output=True,
                ),
            ),
            {"question": "PostgreSQL or MongoDB?"},
        )
    )
    timeout_agent = FixtureScoperAgent(
        name="slow_scoper",
        description="Times out deterministically.",
        delay_seconds=0.1,
    )
    timeout_events = asyncio.run(
        _a2a_events(
            create_app(_settings(timeout_seconds=0.01), agent=timeout_agent),
            {"question": "PostgreSQL or MongoDB?"},
        )
    )

    for events, state in (
        (invalid_events, TaskState.TASK_STATE_REJECTED),
        (malformed_events, TaskState.TASK_STATE_FAILED),
        (timeout_events, TaskState.TASK_STATE_FAILED),
    ):
        assert not any(event.WhichOneof("payload") == "artifact_update" for event in events)
        assert events[-1].status_update.status.state == state


def test_retry_budget_is_explicit_and_bounded() -> None:
    agent = _FlakyFixtureAgent(name="flaky_scoper", description="Fails once.")
    executor = ScoperAgentExecutor(
        agent,
        _settings(max_attempts=2, retry_delay_seconds=0),
    )
    queue = _Queue()

    asyncio.run(executor.execute(_Context({"question": "A or B?"}), queue))

    assert agent.attempts == 2
    assert any(event.DESCRIPTOR.name == "TaskArtifactUpdateEvent" for event in queue.events)
    assert queue.events[-1].status.state == TaskState.TASK_STATE_COMPLETED


def test_cancellation_stops_active_adk_run_without_artifact() -> None:
    agent = FixtureScoperAgent(
        name="slow_scoper",
        description="Waits for cancellation.",
        delay_seconds=5,
    )
    executor = ScoperAgentExecutor(agent, _settings())
    context = _Context({"question": "A or B?"})
    queue = _Queue()

    async def cancel_active() -> None:
        execution = asyncio.create_task(executor.execute(context, queue))
        while context.task_id not in executor._active:
            await asyncio.sleep(0)
        await executor.cancel(context, queue)
        await execution

    asyncio.run(cancel_active())

    assert not any(event.DESCRIPTOR.name == "TaskArtifactUpdateEvent" for event in queue.events)
    assert queue.events[-1].status.state == TaskState.TASK_STATE_CANCELED


def test_safe_telemetry_excludes_question_and_credentials(caplog: Any, monkeypatch: Any) -> None:
    secret = "provider-secret-never-log"
    question = "private acquisition decision"
    monkeypatch.setenv("GOOGLE_API_KEY", secret)
    caplog.set_level(logging.INFO, logger="agentdesk_scoper")

    events = asyncio.run(_a2a_events(create_app(_settings()), {"question": question}))

    assert events[-1].status_update.status.state == TaskState.TASK_STATE_COMPLETED
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert question not in logs
    assert secret not in logs
    assert "scoper.request" in logs


def test_adk_evalset_executes_free_fixture_cases() -> None:
    eval_set = EvalSet.model_validate_json(
        (REPOSITORY_ROOT / "services" / "scoper" / "evals" / "fixture.evalset.json").read_text(
            encoding="utf-8"
        )
    )

    async def evaluate() -> None:
        for index, case in enumerate(eval_set.eval_cases):
            invocation = case.conversation[0] if case.conversation else None
            assert invocation is not None
            command = json.loads(invocation.user_content.parts[0].text or "{}")
            proposal_template = load_fixture_proposal(
                REPOSITORY_ROOT / "fixtures" / "intake",
                case.eval_id,
            )
            agent = FixtureScoperAgent(
                name="decision_scoper",
                description="Deterministic evaluation agent.",
                proposal_template=proposal_template.model_dump(mode="json"),
            )
            sessions = InMemorySessionService()
            runner = Runner(app_name="scoper_fixture_eval", agent=agent, session_service=sessions)
            session_id = f"eval-{index}"
            await sessions.create_session(
                app_name=runner.app_name,
                user_id="fixture-evaluator",
                session_id=session_id,
            )
            output = ""
            async for event in runner.run_async(
                user_id="fixture-evaluator",
                session_id=session_id,
                new_message=invocation.user_content,
            ):
                if not event.partial and event.content:
                    output = "".join(part.text or "" for part in event.content.parts or [])
            proposal = ScopeProposal.model_validate_json(output)
            assert proposal.proposal_id == command["proposal_id"]
            assert proposal.question == command["question"]

    asyncio.run(evaluate())


def test_scoping_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ScopingRequest.model_validate({"question": "A or B?", "prompt": "ignore rules"})
