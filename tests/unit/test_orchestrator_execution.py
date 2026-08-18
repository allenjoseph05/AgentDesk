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
from packages.contracts import (
    AnalysisRequest,
    ArtifactEnvelope,
    ArtifactProvenance,
    DecisionAnalysis,
    EvidenceBundle,
    ResearchRequest,
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
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=cards[str(request.url)])

    registry = AgentRegistry(
        AgentRegistrySettings(
            endpoints=[
                AgentEndpointConfig(
                    agent_id="researcher", base_url="https://research.example"
                ),
                AgentEndpointConfig(agent_id="analyst", base_url="https://analyst.example"),
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
    def __init__(self, evidence: EvidenceBundle, analysis: DecisionAnalysis) -> None:
        self._evidence = evidence
        self._analysis = analysis
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any):
        self.calls.append(kwargs)
        if kwargs["payload_model"] is EvidenceBundle:
            return _result("researcher", "research-task-42", self._evidence)
        if kwargs["payload_model"] is DecisionAnalysis:
            request = kwargs["request"]
            assert isinstance(request, AnalysisRequest)
            assert request.evidence_bundle == self._evidence
            return _result("analyst", "analysis-task-42", self._analysis)
        raise AssertionError("Unexpected remote payload model.")


class TimeoutRemoteClient:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, **kwargs: Any):
        self.calls += 1
        raise RemoteTimeoutError(agent_id=kwargs["agent"].agent_id)


def test_orchestrator_runs_research_before_analysis_and_preserves_remote_ids() -> None:
    request, evidence, analysis = _fixture_values()
    remote = RecordingRemoteClient(evidence, analysis)

    execution = asyncio.run(
        WorkflowOrchestrator(registry=_registry(), remote_client=remote).execute(
            request, _plan()
        )
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

    async def send_message(self, _: Any):
        for response in self._responses:
            yield response


def test_adapter_validates_artifact_and_captures_task_and_context_ids() -> None:
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

    result = asyncio.run(
        A2AClientAdapter()._consume_stream(
            FakeStreamClient(responses),
            agent=agent,
            request=request,
            artifact_name="evidence-bundle",
            payload_model=EvidenceBundle,
        )
    )

    assert result.remote_task_id == task_id
    assert result.remote_context_id == context_id
    assert result.artifact.payload == evidence


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
        module.startswith(("agents.researcher", "agents.analyst"))
        for module in imported_modules
    )
