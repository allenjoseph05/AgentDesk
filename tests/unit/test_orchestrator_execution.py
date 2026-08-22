"""Coordinator A2A adapter and dependency execution tests."""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from a2a.helpers.proto_helpers import new_data_part
from a2a.types import (
    Artifact,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel

from agents.analyst.agent_card import create_agent_card as create_analyst_card
from agents.coordinator.a2a_client import (
    A2AClientAdapter,
    RemoteTaskResult,
    RemoteTimeoutError,
    RemoteTransportError,
)
from agents.coordinator.orchestrator import OrchestrationPlanError, WorkflowOrchestrator
from agents.coordinator.planner import PlannedStep, WorkflowPlan
from agents.coordinator.registry import (
    AgentEndpointConfig,
    AgentRegistry,
    AgentRegistrySettings,
    RegisteredAgent,
)
from agents.researcher.agent_card import create_agent_card as create_research_card
from agents.verifier.agent_card import create_agent_card as create_verifier_card
from packages.contracts import (
    AnalysisRequest,
    ArtifactEnvelope,
    ArtifactProvenance,
    DecisionAnalysis,
    EvidenceBundle,
    RecommendationChallenge,
    ResearchRequest,
    VerificationReport,
)
from packages.testing import load_research_fixture

ROOT = Path(__file__).resolve().parents[2]


def _fixture_values() -> tuple[ResearchRequest, EvidenceBundle, DecisionAnalysis]:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    if fixture.evidence_bundle is None or fixture.decision_analysis is None:
        raise AssertionError("Golden fixture requires evidence and analysis.")
    return fixture.request, fixture.evidence_bundle, fixture.decision_analysis


def _registry() -> AgentRegistry:
    cards = {
        "https://research.example/.well-known/agent-card.json": MessageToDict(
            create_research_card("https://research.example")
        ),
        "https://analyst.example/.well-known/agent-card.json": MessageToDict(
            create_analyst_card("https://analyst.example")
        ),
        "https://verifier.example/.well-known/agent-card.json": MessageToDict(
            create_verifier_card("https://verifier.example")
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=cards[str(request.url)])

    registry = AgentRegistry(
        AgentRegistrySettings(
            endpoints=[
                AgentEndpointConfig(agent_id="researcher", base_url="https://research.example"),
                AgentEndpointConfig(agent_id="analyst", base_url="https://analyst.example"),
                AgentEndpointConfig(agent_id="verifier", base_url="https://verifier.example"),
            ]
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    asyncio.run(registry.refresh())
    return registry


def _plan() -> WorkflowPlan:
    return WorkflowPlan(
        goal="compare_options",
        criteria=["Data integrity", "Schema flexibility"],
        steps=[
            PlannedStep(
                step_id="research",
                skill="web-research",
                scope="Collect evidence.",
                provider_agent_id="researcher",
                provider_base_url="https://research.example",
            ),
            PlannedStep(
                step_id="analysis",
                skill="decision-analysis",
                scope="Analyze evidence.",
                depends_on=["research"],
                provider_agent_id="analyst",
                provider_base_url="https://analyst.example",
            ),
        ],
    )


def _result[PayloadT: BaseModel](
    agent_id: str, task_id: str, payload: PayloadT
) -> RemoteTaskResult[PayloadT]:
    return RemoteTaskResult(
        agent_id=agent_id,
        remote_task_id=task_id,
        remote_context_id="workflow-context",
        artifact=ArtifactEnvelope(
            provenance=ArtifactProvenance(
                producer_agent=agent_id,
                remote_task_id=task_id,
                created_at=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
            ),
            payload=payload,
        ),
    )


class RecordingRemoteClient:
    def __init__(
        self,
        evidence: EvidenceBundle,
        analysis: DecisionAnalysis,
        verification: VerificationReport | None = None,
    ) -> None:
        self._evidence = evidence
        self._analysis = analysis
        self._verification = verification
        self.calls: list[dict[str, Any]] = []
        self.cancel_calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any):
        self.calls.append(kwargs)
        if kwargs["payload_model"] is EvidenceBundle:
            await kwargs["on_task_started"]("research-task-42")
            return _result("researcher", "research-task-42", self._evidence)
        if kwargs["payload_model"] is DecisionAnalysis:
            await kwargs["on_task_started"]("analysis-task-42")
            request = kwargs["request"]
            assert isinstance(request, AnalysisRequest)
            assert request.evidence_bundle == self._evidence
            return _result("analyst", "analysis-task-42", self._analysis)
        if kwargs["payload_model"] is VerificationReport:
            assert self._verification is not None
            await kwargs["on_task_started"]("verification-task-42")
            assert kwargs["request"] == self._evidence
            return _result(
                "verifier",
                "verification-task-42",
                self._verification,
            )
        raise AssertionError("Unexpected remote payload model.")

    async def cancel(self, **kwargs: Any) -> None:
        self.cancel_calls.append(kwargs)


class TimeoutRemoteClient:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, **kwargs: Any):
        self.calls += 1
        raise RemoteTimeoutError(agent_id=kwargs["agent"].agent_id)


class ChallengeRemoteClient:
    def __init__(self, challenge: RecommendationChallenge) -> None:
        self.challenge = challenge
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any):
        self.calls.append(kwargs)
        await kwargs["on_task_started"]("challenge-task-42")
        return _result("analyst", "challenge-task-42", self.challenge)


def test_orchestrator_runs_research_before_analysis_and_preserves_remote_ids() -> None:
    request, evidence, analysis = _fixture_values()
    remote = RecordingRemoteClient(evidence, analysis)

    execution = asyncio.run(
        WorkflowOrchestrator(registry=_registry(), remote_client=remote).execute(request, _plan())
    )

    assert [call["artifact_name"] for call in remote.calls] == [
        "evidence-bundle",
        "decision-analysis",
    ]
    assert isinstance(remote.calls[0]["request"], ResearchRequest)
    assert isinstance(remote.calls[1]["request"], AnalysisRequest)
    assert execution.research.remote_task_id == "research-task-42"
    assert execution.analysis.remote_task_id == "analysis-task-42"
    assert execution.research.artifact.payload == evidence
    assert execution.analysis.artifact.payload == analysis


def test_orchestrator_runs_verification_after_accepted_research_and_analysis() -> None:
    _, evidence, analysis = _fixture_values()
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.verification_report is not None
    remote = RecordingRemoteClient(evidence, analysis, fixture.verification_report)
    scheduled: list[str] = []

    result = asyncio.run(
        WorkflowOrchestrator(registry=_registry(), remote_client=remote).verify(
            evidence,
            on_verification_scheduled=lambda agent: _record_scheduled(scheduled, agent.agent_id),
        )
    )

    assert scheduled == ["verifier"]
    assert remote.calls[0]["artifact_name"] == "verification-report"
    assert remote.calls[0]["payload_model"] is VerificationReport
    assert result.agent_id == "verifier"
    assert result.artifact.payload == fixture.verification_report


def test_orchestrator_routes_challenge_to_the_analyst_artifact_contract() -> None:
    request, evidence, analysis = _fixture_values()
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.recommendation_challenge is not None
    remote = ChallengeRemoteClient(fixture.recommendation_challenge)
    challenge_request = AnalysisRequest(
        question=request.question,
        options=request.options,
        constraints=request.constraints,
        criteria=request.criteria,
        evidence_bundle=evidence,
        mode="challenge_current_recommendation",
        current_recommendation=analysis.recommendation,
    )

    result = asyncio.run(
        WorkflowOrchestrator(registry=_registry(), remote_client=remote).challenge(
            challenge_request
        )
    )

    assert remote.calls[0]["agent"].agent_id == "analyst"
    assert remote.calls[0]["artifact_name"] == "recommendation-challenge"
    assert remote.calls[0]["payload_model"] is RecommendationChallenge
    assert result.artifact.payload == fixture.recommendation_challenge


def test_orchestrator_propagates_remote_cancellation_through_a2a_client() -> None:
    _, evidence, analysis = _fixture_values()
    remote = RecordingRemoteClient(evidence, analysis)
    registry = _registry()
    analyst = registry.get("analyst")
    assert analyst is not None

    asyncio.run(
        WorkflowOrchestrator(registry=registry, remote_client=remote).cancel(
            agent=analyst,
            remote_task_id="analysis-task-cancel",
            timeout_seconds=4,
        )
    )

    assert remote.cancel_calls == [
        {
            "agent": analyst,
            "remote_task_id": "analysis-task-cancel",
            "timeout_seconds": 4,
        }
    ]


def test_orchestrator_reports_remote_task_lifecycle() -> None:
    request, evidence, analysis = _fixture_values()
    remote = RecordingRemoteClient(evidence, analysis)
    lifecycle: list[tuple[str, str, str]] = []

    async def started(agent: RegisteredAgent, task_id: str) -> None:
        lifecycle.append(("started", agent.agent_id, task_id))

    async def finished(agent: RegisteredAgent, task_id: str) -> None:
        lifecycle.append(("finished", agent.agent_id, task_id))

    asyncio.run(
        WorkflowOrchestrator(registry=_registry(), remote_client=remote).execute(
            request,
            _plan(),
            on_remote_task_started=started,
            on_remote_task_finished=finished,
        )
    )

    assert lifecycle == [
        ("started", "researcher", "research-task-42"),
        ("finished", "researcher", "research-task-42"),
        ("started", "analyst", "analysis-task-42"),
        ("finished", "analyst", "analysis-task-42"),
    ]


def test_orchestrator_reports_accepted_research_before_analysis_starts() -> None:
    request, evidence, analysis = _fixture_values()
    remote = RecordingRemoteClient(evidence, analysis)
    accepted: list[tuple[str, str]] = []

    async def research_completed(
        agent: RegisteredAgent,
        result: RemoteTaskResult[EvidenceBundle],
    ) -> None:
        assert [call["artifact_name"] for call in remote.calls] == ["evidence-bundle"]
        accepted.append((agent.agent_id, result.remote_task_id))

    asyncio.run(
        WorkflowOrchestrator(registry=_registry(), remote_client=remote).execute(
            request,
            _plan(),
            on_research_completed=research_completed,
        )
    )

    assert accepted == [("researcher", "research-task-42")]
    assert [call["artifact_name"] for call in remote.calls] == [
        "evidence-bundle",
        "decision-analysis",
    ]


def test_orchestrator_reports_accepted_analysis_at_terminal_boundary() -> None:
    request, evidence, analysis = _fixture_values()
    remote = RecordingRemoteClient(evidence, analysis)
    accepted: list[tuple[str, str]] = []

    async def analysis_completed(
        agent: RegisteredAgent,
        result: RemoteTaskResult[DecisionAnalysis],
    ) -> None:
        assert [call["artifact_name"] for call in remote.calls] == [
            "evidence-bundle",
            "decision-analysis",
        ]
        accepted.append((agent.agent_id, result.remote_task_id))

    execution = asyncio.run(
        WorkflowOrchestrator(registry=_registry(), remote_client=remote).execute(
            request,
            _plan(),
            on_analysis_completed=analysis_completed,
        )
    )

    assert accepted == [("analyst", "analysis-task-42")]
    assert execution.analysis.artifact.payload == analysis


def test_research_failure_prevents_analysis_from_starting() -> None:
    request, _, _ = _fixture_values()
    remote = TimeoutRemoteClient()

    with pytest.raises(RemoteTimeoutError) as error:
        asyncio.run(
            WorkflowOrchestrator(registry=_registry(), remote_client=remote).execute(
                request, _plan()
            )
        )

    assert error.value.code == "timeout"
    assert remote.calls == 1


def test_orchestrator_rejects_stale_or_invalid_provider_assignments() -> None:
    request, _, _ = _fixture_values()
    stale = _plan().model_copy(deep=True)
    stale.steps[0].provider_base_url = "https://invented.example"

    with pytest.raises(OrchestrationPlanError, match="no longer matches"):
        asyncio.run(WorkflowOrchestrator(registry=_registry()).execute(request, stale))


class FakeStreamClient:
    def __init__(self, responses: list[StreamResponse]) -> None:
        self._responses = responses
        self.requests: list[Any] = []

    async def send_message(self, request: Any):
        self.requests.append(request)
        for response in self._responses:
            yield response


def test_adapter_validates_artifact_and_captures_task_and_context_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, evidence, _ = _fixture_values()
    task_id = "remote-research-task"
    context_id = "remote-workflow-context"
    envelope = ArtifactEnvelope[EvidenceBundle](
        provenance=ArtifactProvenance(
            producer_agent="researcher",
            remote_task_id=task_id,
            created_at=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
        ),
        payload=evidence,
    )
    responses = [
        StreamResponse(
            task=Task(
                id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            )
        ),
        StreamResponse(
            artifact_update=TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id="artifact-1",
                    name="evidence-bundle",
                    parts=[new_data_part(envelope.model_dump(mode="json"))],
                ),
                last_chunk=True,
            )
        ),
        StreamResponse(
            status_update=TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
            )
        ),
    ]
    agent = RegisteredAgent(
        agent_id="researcher",
        base_url="https://research.example",
        card=create_research_card("https://research.example"),
    )

    started_task_ids: list[str] = []

    async def task_started(started_task_id: str) -> None:
        started_task_ids.append(started_task_id)

    client = FakeStreamClient(responses)
    monkeypatch.setattr(
        "agents.coordinator.a2a_client.inject_trace_context",
        lambda: {"traceparent": "00-11111111111111111111111111111111-2222222222222222-01"},
    )

    async def consume():
        return await A2AClientAdapter()._consume_stream(
            client,
            agent=agent,
            request=request,
            artifact_name="evidence-bundle",
            payload_model=EvidenceBundle,
            on_task_started=task_started,
        )

    result = asyncio.run(consume())

    assert result.remote_task_id == task_id
    assert result.remote_context_id == context_id
    assert result.artifact.payload == evidence
    assert started_task_ids == [task_id]
    assert MessageToDict(client.requests[0].metadata) == {
        "traceparent": "00-11111111111111111111111111111111-2222222222222222-01"
    }


def test_adapter_sends_official_a2a_cancellation_request(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Any] = []

    class FakeCancelClient:
        def __init__(self, http_client: httpx.AsyncClient) -> None:
            self._http_client = http_client

        async def cancel_task(self, request: Any) -> Task:
            requests.append(request)
            return Task(
                id=request.id,
                context_id="workflow-context",
                status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            )

        async def close(self) -> None:
            await self._http_client.aclose()

    class FakeClientFactory:
        def __init__(self, config: Any) -> None:
            self._config = config

        def create(self, _: Any) -> FakeCancelClient:
            return FakeCancelClient(self._config.httpx_client)

    monkeypatch.setattr("agents.coordinator.a2a_client.ClientFactory", FakeClientFactory)
    agent = RegisteredAgent(
        agent_id="researcher",
        base_url="https://research.example",
        card=create_research_card("https://research.example"),
    )

    asyncio.run(
        A2AClientAdapter().cancel(
            agent=agent,
            remote_task_id="research-task-cancel",
            timeout_seconds=1,
        )
    )

    assert len(requests) == 1
    assert requests[0].id == "research-task-cancel"


class SlowAdapter(A2AClientAdapter):
    async def _consume_stream(self, *args: Any, **kwargs: Any):
        await asyncio.sleep(0.05)
        raise AssertionError("Timeout should interrupt the slow stream.")


class FailingTransportAdapter(A2AClientAdapter):
    async def _consume_stream(self, *args: Any, **kwargs: Any):
        request = httpx.Request("POST", "https://research.example/v1/message:stream")
        raise httpx.ConnectError("fixture connection refused", request=request)


def test_adapter_converts_deadline_to_typed_timeout() -> None:
    request, _, _ = _fixture_values()
    agent = RegisteredAgent(
        agent_id="researcher",
        base_url="https://research.example",
        card=create_research_card("https://research.example"),
    )

    with pytest.raises(RemoteTimeoutError) as error:
        asyncio.run(
            SlowAdapter().execute(
                agent=agent,
                request=request,
                artifact_name="evidence-bundle",
                payload_model=EvidenceBundle,
                timeout_seconds=0.001,
            )
        )

    assert error.value.agent_id == "researcher"


def test_adapter_converts_connection_failure_to_typed_transport_error() -> None:
    request, _, _ = _fixture_values()
    agent = RegisteredAgent(
        agent_id="researcher",
        base_url="https://research.example",
        card=create_research_card("https://research.example"),
    )

    with pytest.raises(RemoteTransportError) as error:
        asyncio.run(
            FailingTransportAdapter().execute(
                agent=agent,
                request=request,
                artifact_name="evidence-bundle",
                payload_model=EvidenceBundle,
                timeout_seconds=1,
            )
        )

    assert error.value.code == "transport_failure"


def test_orchestrator_has_no_ui_or_specialist_implementation_imports() -> None:
    tree = ast.parse(
        (ROOT / "agents" / "coordinator" / "orchestrator.py").read_text(encoding="utf-8")
    )
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "agents.coordinator.agui" not in imported_modules
    assert not any(
        module.startswith(("agents.researcher", "agents.analyst", "agents.verifier"))
        for module in imported_modules
    )


async def _record_scheduled(values: list[str], agent_id: str) -> None:
    values.append(agent_id)
