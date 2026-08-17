"""Protocol-boundary tests for the Coordinator AG-UI endpoint."""

import asyncio
import json
from typing import Any

from httpx import ASGITransport, AsyncClient

from agents.coordinator.main import app


def _input(messages: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": {},
        "messages": messages,
        "tools": [],
        "context": [],
        "forwardedProps": {},
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
    assert events[2]["snapshot"] == {
        "schemaVersion": "1.0",
        "sessionId": "run-1",
        "question": "Should we use PostgreSQL or MongoDB?",
        "status": "planning",
        "activeStep": "accept-research-request",
        "evidenceCount": 0,
        "warnings": [],
        "errors": [],
    }
    assert events[3]["messageId"] == events[4]["messageId"] == events[5]["messageId"]
    assert events[-1]["result"] == {"sessionId": "run-1"}


def test_ag_ui_endpoint_terminates_invalid_input_with_run_error() -> None:
    status, _, events = asyncio.run(_post_events(_input([])))

    assert status == 200
    assert [event["type"] for event in events] == ["RUN_STARTED", "RUN_ERROR"]
    assert events[-1]["code"] == "invalid_research_request"
