"""Coordinator-side contracts for A2A task and context continuity."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

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

from agents.coordinator.a2a_client import A2AClientAdapter, RemoteCallError
from agents.coordinator.registry import RegisteredAgent
from agents.researcher.agent_card import create_agent_card as create_research_card
from packages.contracts import ArtifactEnvelope, ArtifactProvenance, EvidenceBundle
from packages.testing import load_research_fixture

pytestmark = pytest.mark.a2a_contract


class FixtureStreamClient:
    def __init__(self, responses: list[StreamResponse]) -> None:
        self._responses = responses

    async def send_message(self, request: Any):
        del request
        for response in self._responses:
            yield response


def _responses(
    *,
    final_context_id: str,
    final_task_id: str = "research-task-contract",
) -> tuple[list[StreamResponse], EvidenceBundle]:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    task_id = "research-task-contract"
    context_id = "research-context-contract"
    envelope = ArtifactEnvelope(
        provenance=ArtifactProvenance(
            producer_agent="researcher",
            remote_task_id=task_id,
            created_at=datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
        ),
        payload=fixture.evidence_bundle,
    )
    return (
        [
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
                        artifact_id="evidence-contract",
                        name="evidence-bundle",
                        parts=[new_data_part(envelope.model_dump(mode="json"))],
                    ),
                    last_chunk=True,
                )
            ),
            StreamResponse(
                status_update=TaskStatusUpdateEvent(
                    task_id=final_task_id,
                    context_id=final_context_id,
                    status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
                )
            ),
        ],
        fixture.evidence_bundle,
    )


async def _consume(responses: list[StreamResponse], request: EvidenceBundle):
    agent = RegisteredAgent(
        agent_id="researcher",
        base_url="https://research.example",
        card=create_research_card("https://research.example"),
    )
    return await A2AClientAdapter()._consume_stream(
        FixtureStreamClient(responses),
        agent=agent,
        request=request,
        artifact_name="evidence-bundle",
        payload_model=EvidenceBundle,
    )


def test_stream_preserves_one_task_and_context_through_completion() -> None:
    responses, request = _responses(final_context_id="research-context-contract")

    result = asyncio.run(_consume(responses, request))

    assert result.remote_task_id == "research-task-contract"
    assert result.remote_context_id == "research-context-contract"
    assert result.artifact.payload == request


def test_stream_rejects_context_identity_change() -> None:
    responses, request = _responses(final_context_id="substituted-context")

    with pytest.raises(RemoteCallError) as captured:
        asyncio.run(_consume(responses, request))

    assert captured.value.code == "invalid_artifact"
    assert "context identity changed" in str(captured.value)


def test_stream_rejects_task_identity_change() -> None:
    responses, request = _responses(
        final_context_id="research-context-contract",
        final_task_id="substituted-task",
    )

    with pytest.raises(RemoteCallError) as captured:
        asyncio.run(_consume(responses, request))

    assert captured.value.code == "invalid_artifact"
    assert "task identity changed" in str(captured.value)
