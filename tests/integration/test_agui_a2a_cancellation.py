"""End-to-end cancellation propagation from an AG-UI run to an A2A task."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import uvicorn
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import new_text_message
from a2a.types import CancelTaskRequest, Role, SendMessageRequest, TaskState
from a2a.utils.constants import TransportProtocol
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder

from agents.coordinator.agui import stream_run_events
from agents.hello.executor import HelloAgentExecutor
from agents.hello.main import create_app as create_hello_app


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextlib.contextmanager
def _running_slow_hello_agent() -> Iterator[str]:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    application = create_hello_app(
        base_url,
        executor=HelloAgentExecutor(stream_step_delay_seconds=5.0),
    )
    server = uvicorn.Server(
        uvicorn.Config(application, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base_url}/health", timeout=0.25).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("Hello agent did not become ready within 10 seconds.")
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise AssertionError("Hello agent did not stop within 10 seconds.")


class LiveA2ATask:
    """Own the two official A2A clients needed to stream and cancel one task."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._stream_http = httpx.AsyncClient(timeout=10.0)
        self._cancel_http = httpx.AsyncClient(timeout=10.0)
        self._stream_client: Any = None
        self._cancel_client: Any = None
        self._consumer: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self.waiting = asyncio.Event()
        self._remote_task_id: str | None = None
        self.cancel_result_state: TaskState | None = None
        self._startup_error: Exception | None = None

    @classmethod
    async def start(cls, base_url: str, question: str) -> LiveA2ATask:
        task = cls(base_url)
        config = {
            "streaming": True,
            "supported_protocol_bindings": [TransportProtocol.HTTP_JSON],
        }
        task._stream_client = await ClientFactory(
            ClientConfig(httpx_client=task._stream_http, **config)
        ).create_from_url(base_url)
        task._cancel_client = await ClientFactory(
            ClientConfig(httpx_client=task._cancel_http, **config)
        ).create_from_url(base_url)
        task._consumer = asyncio.create_task(task._consume(question))
        await asyncio.wait_for(task._ready.wait(), timeout=5)
        if task._startup_error is not None:
            raise RuntimeError("A2A task did not start.") from task._startup_error
        return task

    @property
    def remote_task_id(self) -> str:
        if self._remote_task_id is None:
            raise RuntimeError("A2A task ID is not available yet.")
        return self._remote_task_id

    async def _consume(self, question: str) -> None:
        try:
            request = SendMessageRequest(
                message=new_text_message(f"stream: {question}", role=Role.ROLE_USER)
            )
            async for response in self._stream_client.send_message(request):
                if response.HasField("task"):
                    self._remote_task_id = response.task.id
                    self._ready.set()
        except Exception as error:
            self._startup_error = error
            raise
        finally:
            self._ready.set()

    async def wait(self) -> None:
        self.waiting.set()
        if self._consumer is None:
            raise RuntimeError("A2A stream consumer was not started.")
        await asyncio.shield(self._consumer)

    async def cancel(self) -> None:
        cancelled = await self._cancel_client.cancel_task(CancelTaskRequest(id=self.remote_task_id))
        self.cancel_result_state = cancelled.status.state
        # SDK 1.1.2 does not reliably echo an early cancellation on the original
        # send-message stream, so the cancel response is authoritative in this spike.
        if self._consumer is not None and not self._consumer.done():
            self._consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer

    async def aclose(self) -> None:
        if self._consumer is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._consumer), timeout=3)
            except TimeoutError:
                self._consumer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._consumer
        if self._stream_client is not None:
            await self._stream_client.close()
        elif not self._stream_http.is_closed:
            await self._stream_http.aclose()
        if self._cancel_client is not None:
            await self._cancel_client.close()
        elif not self._cancel_http.is_closed:
            await self._cancel_http.aclose()


class LiveA2ATaskFactory:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.task: LiveA2ATask | None = None

    async def start(self, question: str) -> LiveA2ATask:
        self.task = await LiveA2ATask.start(self.base_url, question)
        return self.task


def _run_input() -> RunAgentInput:
    question = "Should we use PostgreSQL or MongoDB?"
    return RunAgentInput.model_validate(
        {
            "threadId": "thread-cancel",
            "runId": "run-cancel",
            "state": {},
            "messages": [{"id": "message-1", "role": "user", "content": question}],
            "tools": [],
            "context": [],
            "forwardedProps": {
                "agentdesk": {
                    "schemaVersion": "1.0",
                    "actionId": "action-cancel",
                    "type": "start_research",
                    "sessionId": None,
                    "payload": {
                        "question": question,
                        "options": [],
                        "constraints": [],
                        "criteria": [],
                        "desiredDepth": "normal",
                    },
                }
            },
        }
    )


async def _cancel_coordinator_stream(base_url: str) -> tuple[list[dict[str, Any]], LiveA2ATask]:
    factory = LiveA2ATaskFactory(base_url)
    stream: AsyncIterator[str] = stream_run_events(
        _run_input(),
        EventEncoder(accept="text/event-stream"),
        factory,
    )
    events = [json.loads((await anext(stream)).removeprefix("data: ")) for _ in range(4)]
    if factory.task is None:
        raise AssertionError("Coordinator did not start the A2A task.")

    pending_event = asyncio.create_task(anext(stream))
    await factory.task.waiting.wait()
    pending_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_event
    return events, factory.task


def test_cancelled_ag_ui_stream_cancels_one_live_a2a_task() -> None:
    with _running_slow_hello_agent() as base_url:
        events, task = asyncio.run(_cancel_coordinator_stream(base_url))

    assert events[-1]["type"] == "STATE_SNAPSHOT"
    assert events[-1]["snapshot"]["agents"][0]["remoteTaskId"] == task.remote_task_id
    assert task.cancel_result_state == TaskState.TASK_STATE_CANCELED
