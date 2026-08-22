"""Process-level A2A task streaming and cancellation coverage."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import new_text_message
from a2a.types import CancelTaskRequest, Role, SendMessageRequest, Task, TaskState
from a2a.utils.constants import TransportProtocol

from agents.hello.stream_client import project_event

ROOT = Path(__file__).resolve().parents[2]
STREAM_FIXTURE = ROOT / "tests" / "fixtures" / "a2a" / "hello_task_stream.json"


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def _running_hello_agent() -> Iterator[str]:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["HELLO_AGENT_URL"] = base_url
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "agents.hello.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if server.poll() is not None:
                stdout, stderr = server.communicate()
                raise AssertionError(
                    f"Hello agent stopped early.\nstdout: {stdout}\nstderr: {stderr}"
                )
            try:
                response = httpx.get(f"{base_url}/health", timeout=0.25)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("Hello agent did not become ready within 10 seconds.")
        yield base_url
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def test_separate_client_observes_incremental_task_stream() -> None:
    expected = json.loads(STREAM_FIXTURE.read_text(encoding="utf-8"))

    with _running_hello_agent() as base_url:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "agents.hello.stream_client",
                "stream: Allen",
                "--base-url",
                base_url,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    observed = json.loads(completed.stdout)
    working_updates = [
        event
        for event in observed
        if event.get("kind") == "status_update" and event.get("state") == "TASK_STATE_WORKING"
    ]

    assert observed == expected["events"]
    assert len(working_updates) >= 2
    assert observed[-1]["state"] == "TASK_STATE_COMPLETED"


async def _cancel_after_first_working_update(base_url: str) -> tuple[list[dict], Task]:
    stream_http = httpx.AsyncClient(timeout=10.0)
    cancel_http = httpx.AsyncClient(timeout=10.0)
    stream_client = None
    cancel_client = None
    try:
        config = {
            "streaming": True,
            "supported_protocol_bindings": [TransportProtocol.HTTP_JSON],
        }
        stream_client = await ClientFactory(
            ClientConfig(httpx_client=stream_http, **config)
        ).create_from_url(base_url)
        cancel_client = await ClientFactory(
            ClientConfig(httpx_client=cancel_http, **config)
        ).create_from_url(base_url)
        request = SendMessageRequest(
            message=new_text_message("stream: cancellation", role=Role.ROLE_USER)
        )
        events: list[dict] = []
        task_id: str | None = None
        canceled_task: Task | None = None

        async for response in stream_client.send_message(request):
            events.append(project_event(response))
            if response.HasField("task"):
                task_id = response.task.id
            if (
                response.HasField("status_update")
                and response.status_update.status.state == TaskState.TASK_STATE_WORKING
                and canceled_task is None
            ):
                if task_id is None:
                    raise AssertionError("Stream did not expose a task ID before working state.")
                canceled_task = await cancel_client.cancel_task(CancelTaskRequest(id=task_id))

        if canceled_task is None:
            raise AssertionError("Task completed before the cancellation request was sent.")
        return events, canceled_task
    finally:
        if stream_client is not None:
            await stream_client.close()
        elif not stream_http.is_closed:
            await stream_http.aclose()
        if cancel_client is not None:
            await cancel_client.close()
        elif not cancel_http.is_closed:
            await cancel_http.aclose()


def test_official_cancel_path_returns_terminal_canceled_task() -> None:
    with _running_hello_agent() as base_url:
        events, canceled_task = asyncio.run(_cancel_after_first_working_update(base_url))

    assert canceled_task.status.state == TaskState.TASK_STATE_CANCELED
    assert events[-1] == {
        "kind": "status_update",
        "state": "TASK_STATE_CANCELED",
        "text": "Greeting task cancelled.",
    }
    assert all(event["kind"] != "artifact_update" for event in events)
