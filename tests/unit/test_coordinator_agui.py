"""Protocol-boundary tests for the Coordinator AG-UI endpoint."""

import asyncio
import json
from typing import Any

import pytest
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agents.coordinator.agui import stream_run_events
from agents.coordinator.main import create_app


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


def _input(
    messages: list[dict[str, str]],
    action: dict[str, Any] | None = None,
    *,
    thread_id: str = "thread-1",
    run_id: str = "run-1",
) -> dict[str, Any]:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": {},
        "messages": messages,
        "tools": [],
        "context": [],
        "forwardedProps": {"agentdesk": action or _start_action()},
    }


async def _post_events(
    payload: dict[str, Any], application: FastAPI | None = None
) -> tuple[int, str, list[dict[str, Any]]]:
    application = application or create_app()
    transport = ASGITransport(app=application)
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


class BlockingTask:
    remote_task_id = "remote-task-1"

    def __init__(self) -> None:
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()
        self.cancel_calls = 0
        self.close_calls = 0

    async def wait(self) -> None:
        self.waiting.set()
        await self.release.wait()

    async def cancel(self) -> None:
        self.cancel_calls += 1
        self.release.set()

    async def aclose(self) -> None:
        self.close_calls += 1


class BlockingTaskFactory:
    def __init__(self, task: BlockingTask) -> None:
        self.task = task

    async def start(self, question: str) -> BlockingTask:
        assert question == "Should we use PostgreSQL or MongoDB?"
        return self.task


class FailingTaskFactory:
    async def start(self, question: str) -> BlockingTask:
        raise RuntimeError(f"Remote task failed for: {question}")


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
    assert events[-1]["result"] == {
        "threadId": "thread-1",
        "runId": "run-1",
        "sessionId": "run-1",
        "actionId": "action-1",
        "status": "completed",
        "remoteTasks": [],
    }


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


def test_stream_cancellation_invokes_active_a2a_task_hook_once() -> None:
    async def cancel_while_waiting() -> tuple[list[dict[str, Any]], BlockingTask]:
        task = BlockingTask()
        input_data = RunAgentInput.model_validate(
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
        stream = stream_run_events(
            input_data,
            EventEncoder(accept="text/event-stream"),
            BlockingTaskFactory(task),
        )
        observed = []
        for _ in range(4):
            observed.append(json.loads((await anext(stream)).removeprefix("data: ")))

        pending_event = asyncio.create_task(anext(stream))
        await task.waiting.wait()
        pending_event.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending_event
        return observed, task

    events, task = asyncio.run(cancel_while_waiting())

    assert [event["type"] for event in events] == [
        "RUN_STARTED",
        "STEP_STARTED",
        "STATE_SNAPSHOT",
        "STATE_DELTA",
    ]
    changes = {operation["path"]: operation["value"] for operation in events[-1]["delta"]}
    assert changes["/status"] == "researching"
    assert changes["/agents"][0]["remoteTaskId"] == "remote-task-1"
    assert task.cancel_calls == 1
    assert task.close_calls == 1


def test_runtime_failure_emits_one_terminal_run_error_and_stops() -> None:
    payload = _input(
        [
            {
                "id": "message-1",
                "role": "user",
                "content": "Should we use PostgreSQL or MongoDB?",
            }
        ]
    )
    _, _, events = asyncio.run(_post_events(payload, create_app(FailingTaskFactory())))

    assert [event["type"] for event in events] == [
        "RUN_STARTED",
        "STEP_STARTED",
        "STATE_SNAPSHOT",
        "RUN_ERROR",
    ]
    assert events[-1]["code"] == "coordinator_run_failed"
    assert sum(event["type"] in {"RUN_ERROR", "RUN_FINISHED"} for event in events) == 1


def test_reconnect_uses_new_run_on_same_thread_and_gets_fresh_snapshot() -> None:
    message = {
        "id": "message-1",
        "role": "user",
        "content": "Should we use PostgreSQL or MongoDB?",
    }

    _, _, first = asyncio.run(_post_events(_input([message], run_id="run-before-abort")))
    _, _, second = asyncio.run(_post_events(_input([message], run_id="run-after-reconnect")))

    first_snapshot = next(event["snapshot"] for event in first if event["type"] == "STATE_SNAPSHOT")
    second_snapshot = next(
        event["snapshot"] for event in second if event["type"] == "STATE_SNAPSHOT"
    )
    assert first[0]["threadId"] == second[0]["threadId"] == "thread-1"
    assert first[0]["runId"] != second[0]["runId"]
    assert first_snapshot["sessionId"] == "run-before-abort"
    assert second_snapshot["sessionId"] == "run-after-reconnect"
    assert second_snapshot["schemaVersion"] == "1.0"
