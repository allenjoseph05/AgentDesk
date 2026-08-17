"""Protocol-boundary tests for the Coordinator AG-UI endpoint."""

import asyncio
import json
from typing import Any

from httpx import ASGITransport, AsyncClient

from agents.coordinator.main import app


def _start_action() -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "actionId": "action-1",
        "type": "start_research",
        "sessionId": None,
        "payload": {
            "question": "Should we use PostgreSQL or MongoDB?",
            "options": [],
            "constraints": [],
            "criteria": [],
            "desiredDepth": "normal",
        },
    }


def _input(messages: list[dict[str, str]], action: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": {},
        "messages": messages,
        "tools": [],
        "context": [],
        "forwardedProps": {"agentdesk": action or _start_action()},
    }


async def _post_events(payload: dict[str, Any]) -> tuple[int, str, list[dict[str, Any]]]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/ag-ui",
            json=payload,
            headers={"Accept": "text/event-stream"},
        )
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    return response.status_code, response.headers["content-type"], events


def test_ag_ui_endpoint_streams_lifecycle_state_step_and_message_events() -> None:
    status, content_type, events = asyncio.run(
        _post_events(
            _input(
                [
                    {
                        "id": "message-1",
                        "role": "user",
                        "content": "Should we use PostgreSQL or MongoDB?",
                    }
                ]
            )
        )
    )

    assert status == 200
    assert content_type.startswith("text/event-stream")
    assert [event["type"] for event in events] == [
        "RUN_STARTED",
        "STEP_STARTED",
        "STATE_SNAPSHOT",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "STEP_FINISHED",
        "RUN_FINISHED",
    ]
    assert events[0] == {"type": "RUN_STARTED", "threadId": "thread-1", "runId": "run-1"}
    snapshot = events[2]["snapshot"]
    assert snapshot["schemaVersion"] == "1.0"
    assert snapshot["sessionId"] == "run-1"
    assert snapshot["question"] == "Should we use PostgreSQL or MongoDB?"
    assert snapshot["status"] == "planning"
    assert snapshot["activeStep"] == "accept-research-request"
    assert snapshot["agents"] == snapshot["evidence"] == snapshot["claims"] == []
    assert snapshot["evidenceCount"] == 0
    assert snapshot["analysis"] is snapshot["verification"] is None
    assert snapshot["warnings"] == snapshot["errors"] == snapshot["availableActions"] == []
    assert snapshot["lastUpdatedAt"].endswith("Z")
    assert events[3]["messageId"] == events[4]["messageId"] == events[5]["messageId"]
    assert events[-1]["result"] == {"sessionId": "run-1", "actionId": "action-1"}


def test_ag_ui_endpoint_rejects_message_action_disagreement() -> None:
    status, _, events = asyncio.run(_post_events(_input([])))

    assert status == 200
    assert [event["type"] for event in events] == ["RUN_STARTED", "RUN_ERROR"]
    assert events[-1]["code"] == "action_message_mismatch"


def test_ag_ui_endpoint_rejects_invalid_action_envelope() -> None:
    payload = _input(
        [{"id": "message-1", "role": "user", "content": "Question"}],
        action={"schemaVersion": "99"},
    )
    _, _, events = asyncio.run(_post_events(payload))

    assert [event["type"] for event in events] == ["RUN_STARTED", "RUN_ERROR"]
    assert events[-1]["code"] == "invalid_agentdesk_action"
