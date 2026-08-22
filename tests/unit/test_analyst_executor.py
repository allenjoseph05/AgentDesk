"""A2A event tests for the Analyst Agent executor."""

import asyncio
import json
from typing import Any

from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import Event, EventQueue
from a2a.types import (
    Role,
    SendMessageRequest,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
)
from google.protobuf.json_format import MessageToDict

from agents.analyst import DecisionAnalyzer
from agents.analyst.executor import (
    FINAL_ANALYSIS_ARTIFACT,
    FINAL_CHALLENGE_ARTIFACT,
    AnalystAgentExecutor,
)
from packages.contracts import (
    AnalysisRequest,
    ArtifactEnvelope,
    DecisionAnalysis,
    RecommendationChallenge,
)
from packages.llm import FakeLLMProvider
from packages.testing import load_research_fixture


class RecordingEventQueue(EventQueue):
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def enqueue_event(self, event: Event) -> None:
        self.events.append(event)


def _context(payload: dict[str, Any] | str) -> RequestContext:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return RequestContext(
        ServerCallContext(),
        request=SendMessageRequest(
            message=new_text_message(text, media_type="application/json", role=Role.ROLE_USER)
        ),
        task_id="analyst-task-1",
        context_id="analyst-context-1",
    )


def _configured_executor() -> tuple[AnalystAgentExecutor, AnalysisRequest]:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    if fixture.evidence_bundle is None or fixture.decision_analysis is None:
        raise AssertionError("Golden fixture must contain evidence and analysis.")
    request = AnalysisRequest(
        question=fixture.request.question,
        options=fixture.request.options,
        constraints=fixture.request.constraints,
        criteria=fixture.request.criteria,
        evidence_bundle=fixture.evidence_bundle,
    )
    analyzer = DecisionAnalyzer(FakeLLMProvider({DecisionAnalysis: fixture.decision_analysis}))
    return AnalystAgentExecutor(analyzer), request


def _artifact_data(event: TaskArtifactUpdateEvent) -> dict[str, Any]:
    value = MessageToDict(event.artifact.parts[0].data)
    if not isinstance(value, dict):
        raise AssertionError("Expected object-valued analysis artifact.")
    return value


def _configured_challenge_executor() -> tuple[AnalystAgentExecutor, AnalysisRequest]:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    if (
        fixture.evidence_bundle is None
        or fixture.decision_analysis is None
        or fixture.recommendation_challenge is None
    ):
        raise AssertionError("Golden fixture must contain evidence, analysis, and challenge.")
    request = AnalysisRequest(
        question=fixture.request.question,
        options=fixture.request.options,
        constraints=fixture.request.constraints,
        criteria=fixture.request.criteria,
        evidence_bundle=fixture.evidence_bundle,
        mode="challenge_current_recommendation",
        current_recommendation=fixture.decision_analysis.recommendation,
    )
    analyzer = DecisionAnalyzer(
        FakeLLMProvider({RecommendationChallenge: fixture.recommendation_challenge})
    )
    return AnalystAgentExecutor(analyzer), request


def test_executor_emits_working_status_validated_artifact_and_completion() -> None:
    executor, request = _configured_executor()
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context(request.model_dump(mode="json")), queue))

    assert isinstance(queue.events[0], Task)
    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    artifacts = [event for event in queue.events if isinstance(event, TaskArtifactUpdateEvent)]
    assert [event.status.state for event in statuses] == [
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_COMPLETED,
    ]
    assert [get_message_text(event.status.message) for event in statuses] == [
        "Analyzing options against supplied evidence.",
        "Decision analysis completed.",
    ]
    assert len(artifacts) == 1
    assert artifacts[0].artifact.name == FINAL_ANALYSIS_ARTIFACT
    assert artifacts[0].last_chunk is True
    assert MessageToDict(artifacts[0].artifact.metadata) == {
        "partial": False,
        "schemaVersion": "1.0",
    }

    envelope = ArtifactEnvelope[DecisionAnalysis].model_validate(_artifact_data(artifacts[0]))
    assert envelope.provenance.producer_agent == "analyst"
    assert envelope.provenance.remote_task_id == "analyst-task-1"
    assert envelope.payload.recommendation == "PostgreSQL"


def test_executor_emits_challenge_as_a_separate_typed_artifact() -> None:
    executor, request = _configured_challenge_executor()
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context(request.model_dump(mode="json")), queue))

    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    artifacts = [event for event in queue.events if isinstance(event, TaskArtifactUpdateEvent)]
    assert [get_message_text(event.status.message) for event in statuses] == [
        "Challenging the current recommendation using supplied evidence.",
        "Recommendation challenge completed.",
    ]
    assert [event.status.state for event in statuses] == [
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_COMPLETED,
    ]
    assert len(artifacts) == 1
    assert artifacts[0].artifact.name == FINAL_CHALLENGE_ARTIFACT
    envelope = ArtifactEnvelope[RecommendationChallenge].model_validate(
        _artifact_data(artifacts[0])
    )
    assert envelope.provenance.producer_agent == "analyst"
    assert envelope.payload.current_recommendation == "PostgreSQL"
    assert envelope.payload.strongest_alternative == "MongoDB"


def test_executor_rejects_invalid_analysis_request() -> None:
    executor, _ = _configured_executor()
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context({"question": "Compare databases"}), queue))

    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    assert len(statuses) == 1
    assert statuses[0].status.state == TaskState.TASK_STATE_REJECTED
    assert "AnalysisRequest schema" in get_message_text(statuses[0].status.message)
    assert not any(isinstance(event, TaskArtifactUpdateEvent) for event in queue.events)


def test_executor_reports_grounding_failure_without_an_artifact() -> None:
    _, request = _configured_executor()
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    if fixture.decision_analysis is None:
        raise AssertionError("Golden fixture must contain analysis.")
    candidate = fixture.decision_analysis.model_copy(deep=True)
    candidate.criteria[0].supporting_claim_ids = ["invented-claim"]
    executor = AnalystAgentExecutor(
        DecisionAnalyzer(FakeLLMProvider({DecisionAnalysis: candidate}))
    )
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context(request.model_dump(mode="json")), queue))

    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    assert [event.status.state for event in statuses] == [
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_FAILED,
    ]
    assert "unsupported_claim_reference" in get_message_text(statuses[-1].status.message)
    assert not any(isinstance(event, TaskArtifactUpdateEvent) for event in queue.events)


def test_cancel_emits_one_terminal_cancelled_status() -> None:
    queue = RecordingEventQueue()

    asyncio.run(AnalystAgentExecutor().cancel(_context("{}"), queue))

    assert len(queue.events) == 1
    event = queue.events[0]
    assert isinstance(event, TaskStatusUpdateEvent)
    assert event.status.state == TaskState.TASK_STATE_CANCELED
    assert get_message_text(event.status.message) == "Analysis task cancelled."
