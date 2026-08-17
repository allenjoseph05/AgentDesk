"""A2A event-stream tests for the Research Agent executor."""

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

from agents.researcher import ResearchSynthesizer, create_fixture_providers
from agents.researcher.executor import (
    FINAL_EVIDENCE_ARTIFACT,
    PARTIAL_SOURCES_ARTIFACT,
    ResearchAgentExecutor,
)
from packages.contracts import ArtifactEnvelope, EvidenceBundle, ResearchRequest
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
        task_id="research-task-1",
        context_id="research-context-1",
    )


def _fixture_executor(fixture_id: str) -> tuple[ResearchAgentExecutor, ResearchRequest]:
    fixture = load_research_fixture(fixture_id)
    if fixture.evidence_bundle is None:
        raise AssertionError("Successful executor fixture requires an evidence bundle.")
    search_provider, source_provider = create_fixture_providers(fixture_id)
    synthesizer = ResearchSynthesizer(
        search_provider=search_provider,
        source_provider=source_provider,
        llm_provider=FakeLLMProvider({EvidenceBundle: fixture.evidence_bundle}),
    )
    return ResearchAgentExecutor(synthesizer), fixture.request


def _data(artifact_event: TaskArtifactUpdateEvent) -> dict[str, Any]:
    value = MessageToDict(artifact_event.artifact.parts[0].data)
    if not isinstance(value, dict):
        raise AssertionError("Expected an object-valued artifact part.")
    return value


def test_executor_streams_real_phases_partial_sources_final_bundle_and_completion() -> None:
    executor, request = _fixture_executor("postgresql-vs-mongodb-golden")
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context(request.model_dump(mode="json")), queue))

    assert isinstance(queue.events[0], Task)
    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    artifacts = [event for event in queue.events if isinstance(event, TaskArtifactUpdateEvent)]
    assert [event.status.state for event in statuses] == [
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_COMPLETED,
    ]
    status_text = [get_message_text(event.status.message) for event in statuses]
    assert status_text == [
        "Searching for relevant sources.",
        "Fetching 2 relevant source(s).",
        "Synthesizing evidence from 2 retrieved source(s).",
        "Evidence synthesis completed.",
    ]
    assert all("%" not in text for text in status_text)

    assert [event.artifact.name for event in artifacts] == [
        PARTIAL_SOURCES_ARTIFACT,
        FINAL_EVIDENCE_ARTIFACT,
    ]
    assert all(event.last_chunk for event in artifacts)
    partial = _data(artifacts[0])
    assert partial == {
        "schema_version": "1.0",
        "phase": "sources_collected",
        "source_ids": ["evidence-pg", "evidence-mongo"],
        "failed_source_ids": [],
    }
    assert MessageToDict(artifacts[0].artifact.metadata) == {
        "partial": True,
        "schemaVersion": "1.0",
    }

    envelope = ArtifactEnvelope[EvidenceBundle].model_validate(_data(artifacts[1]))
    assert envelope.provenance.producer_agent == "researcher"
    assert envelope.provenance.remote_task_id == "research-task-1"
    assert envelope.payload.question == request.question
    assert {claim.id for claim in envelope.payload.claims} == {"claim-pg", "claim-mongo"}
    assert queue.events[-1] is statuses[-1]


def test_invalid_request_is_rejected_without_starting_research() -> None:
    executor, _ = _fixture_executor("postgresql-vs-mongodb-golden")
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context({"question": " "}), queue))

    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    assert len(statuses) == 1
    assert statuses[0].status.state == TaskState.TASK_STATE_REJECTED
    assert "ResearchRequest schema" in get_message_text(statuses[0].status.message)
    assert not any(isinstance(event, TaskArtifactUpdateEvent) for event in queue.events)


def test_tool_failure_ends_in_failed_state_without_final_artifact() -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-failure")
    search_provider, source_provider = create_fixture_providers(fixture.fixture_id)
    executor = ResearchAgentExecutor(
        ResearchSynthesizer(
            search_provider=search_provider,
            source_provider=source_provider,
            llm_provider=FakeLLMProvider({}),
        )
    )
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context(fixture.request.model_dump(mode="json")), queue))

    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    assert [event.status.state for event in statuses] == [
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_FAILED,
    ]
    assert "fixture_source_unavailable" in get_message_text(statuses[-1].status.message)
    assert not any(isinstance(event, TaskArtifactUpdateEvent) for event in queue.events)


def test_cancel_emits_one_terminal_cancelled_status() -> None:
    queue = RecordingEventQueue()

    asyncio.run(ResearchAgentExecutor().cancel(_context("{}"), queue))

    assert len(queue.events) == 1
    event = queue.events[0]
    assert isinstance(event, TaskStatusUpdateEvent)
    assert event.status.state == TaskState.TASK_STATE_CANCELED
    assert get_message_text(event.status.message) == "Research task cancelled."
