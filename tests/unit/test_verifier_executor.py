"""A2A event tests for the Verifier Agent executor."""

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

from agents.verifier import ClaimVerifier
from agents.verifier.executor import FINAL_VERIFICATION_ARTIFACT, VerifierAgentExecutor
from packages.contracts import ArtifactEnvelope, EvidenceBundle, VerificationReport
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
        task_id="verifier-task-1",
        context_id="verifier-context-1",
    )


def _configured_executor(
    fixture_id: str = "postgresql-vs-mongodb-golden",
) -> tuple[VerifierAgentExecutor, EvidenceBundle]:
    fixture = load_research_fixture(fixture_id)
    if fixture.evidence_bundle is None or fixture.verification_report is None:
        raise AssertionError("Verification fixture must contain evidence and a report.")
    verifier = ClaimVerifier(
        FakeLLMProvider({VerificationReport: fixture.verification_report})
    )
    return VerifierAgentExecutor(verifier), fixture.evidence_bundle


def _artifact_data(event: TaskArtifactUpdateEvent) -> dict[str, Any]:
    value = MessageToDict(event.artifact.parts[0].data)
    if not isinstance(value, dict):
        raise AssertionError("Expected object-valued verification artifact.")
    return value


def test_executor_emits_working_status_validated_artifact_and_completion() -> None:
    executor, bundle = _configured_executor()
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context(bundle.model_dump(mode="json")), queue))

    assert isinstance(queue.events[0], Task)
    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    artifacts = [event for event in queue.events if isinstance(event, TaskArtifactUpdateEvent)]
    assert [event.status.state for event in statuses] == [
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_COMPLETED,
    ]
    assert [get_message_text(event.status.message) for event in statuses] == [
        "Verifying claims against supplied evidence.",
        "Claim verification completed.",
    ]
    assert len(artifacts) == 1
    assert artifacts[0].artifact.name == FINAL_VERIFICATION_ARTIFACT
    assert artifacts[0].last_chunk is True
    assert MessageToDict(artifacts[0].artifact.metadata) == {
        "partial": False,
        "schemaVersion": "1.0",
    }

    envelope = ArtifactEnvelope[VerificationReport].model_validate(_artifact_data(artifacts[0]))
    assert envelope.provenance.producer_agent == "verifier"
    assert envelope.provenance.remote_task_id == "verifier-task-1"
    assert [result.claim_id for result in envelope.payload.results] == [
        claim.id for claim in bundle.claims
    ]


def test_executor_rejects_invalid_evidence_input() -> None:
    executor, _ = _configured_executor()
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context({"question": "Compare databases"}), queue))

    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    assert len(statuses) == 1
    assert statuses[0].status.state == TaskState.TASK_STATE_REJECTED
    assert "EvidenceBundle schema" in get_message_text(statuses[0].status.message)
    assert not any(isinstance(event, TaskArtifactUpdateEvent) for event in queue.events)


def test_executor_completes_with_insufficient_evidence_verdicts() -> None:
    executor, bundle = _configured_executor("postgresql-vs-mongodb-contradictory")
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context(bundle.model_dump(mode="json")), queue))

    artifact = next(
        event for event in queue.events if isinstance(event, TaskArtifactUpdateEvent)
    )
    report = ArtifactEnvelope[VerificationReport].model_validate(
        _artifact_data(artifact)
    ).payload
    assert {result.verdict for result in report.results} == {"insufficient_evidence"}
    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    assert statuses[-1].status.state == TaskState.TASK_STATE_COMPLETED


def test_executor_reports_grounding_failure_without_an_artifact() -> None:
    _, bundle = _configured_executor()
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    if fixture.verification_report is None:
        raise AssertionError("Golden fixture must contain verification.")
    candidate = fixture.verification_report.model_copy(deep=True)
    candidate.results[0].evidence_ids = ["invented-evidence"]
    executor = VerifierAgentExecutor(
        ClaimVerifier(FakeLLMProvider({VerificationReport: candidate}))
    )
    queue = RecordingEventQueue()

    asyncio.run(executor.execute(_context(bundle.model_dump(mode="json")), queue))

    statuses = [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]
    assert [event.status.state for event in statuses] == [
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_FAILED,
    ]
    assert "unknown_evidence_reference" in get_message_text(statuses[-1].status.message)
    assert not any(isinstance(event, TaskArtifactUpdateEvent) for event in queue.events)


def test_cancel_emits_one_terminal_cancelled_status() -> None:
    queue = RecordingEventQueue()

    asyncio.run(VerifierAgentExecutor().cancel(_context("{}"), queue))

    assert len(queue.events) == 1
    event = queue.events[0]
    assert isinstance(event, TaskStatusUpdateEvent)
    assert event.status.state == TaskState.TASK_STATE_CANCELED
    assert get_message_text(event.status.message) == "Verification task cancelled."
