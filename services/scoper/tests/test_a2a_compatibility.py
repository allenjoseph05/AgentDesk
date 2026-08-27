"""Process-level conformance evidence for the selected ADK/A2A adapter."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.types import CancelTaskRequest, Role, SendMessageRequest, Task, TaskState
from a2a.utils.constants import TransportProtocol
from google.protobuf.json_format import MessageToDict

from agentdesk_scoper.fixture_agent import SCOPE_FIXTURE

SCOPER_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_MODULE = "agentdesk_scoper.adapter_bridge:app"


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def _running_adapter(
    *,
    delay_seconds: float = 0.0,
    malformed_output: bool = False,
    timeout_seconds: float = 2.0,
) -> Iterator[str]:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SCOPER_ROOT / "src")
    environment["SCOPER_COMPAT_URL"] = base_url
    environment["SCOPER_FIXTURE_DELAY_SECONDS"] = str(delay_seconds)
    environment["SCOPER_FIXTURE_MALFORMED"] = "1" if malformed_output else "0"
    environment["SCOPER_COMPAT_TIMEOUT_SECONDS"] = str(timeout_seconds)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            ADAPTER_MODULE,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=SCOPER_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    failure: BaseException | None = None
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if server.poll() is not None:
                stdout, stderr = server.communicate()
                raise AssertionError(
                    f"Adapter probe stopped early.\nstdout: {stdout}\nstderr: {stderr}"
                )
            try:
                response = httpx.get(f"{base_url}/.well-known/agent-card.json", timeout=0.25)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("Adapter probe did not become ready within 15 seconds.")
        yield base_url
    except BaseException as error:
        failure = error
        raise
    finally:
        server.terminate()
        try:
            stdout, stderr = server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            stdout, stderr = server.communicate(timeout=5)
        if failure is not None and (stdout or stderr):
            failure.add_note(f"Adapter stdout:\n{stdout}\nAdapter stderr:\n{stderr}")


async def _create_client(base_url: str) -> tuple[Any, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(timeout=10.0)
    client = await ClientFactory(
        ClientConfig(
            streaming=True,
            httpx_client=http_client,
            supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
        )
    ).create_from_url(base_url)
    return client, http_client


async def _read_native_card(native_app: Any) -> tuple[httpx.Response, list[Any]]:
    async with native_app.router.lifespan_context(native_app):
        routes = list(native_app.routes)
        transport = httpx.ASGITransport(app=native_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8010",
        ) as client:
            return await client.get("/.well-known/agent-card.json"), routes


def _project_event(response: Any) -> dict[str, Any]:
    event_type = response.WhichOneof("payload")
    if event_type == "task":
        return {
            "kind": "task",
            "task_id": response.task.id,
            "state": TaskState.Name(response.task.status.state),
        }
    if event_type == "status_update":
        status = response.status_update.status
        return {
            "kind": "status",
            "task_id": response.status_update.task_id,
            "state": TaskState.Name(status.state),
            "text": get_message_text(status.message) if status.HasField("message") else "",
        }
    if event_type == "artifact_update":
        artifact = response.artifact_update.artifact
        return {
            "kind": "artifact",
            "task_id": response.artifact_update.task_id,
            "part_kind": "data" if artifact.parts[0].HasField("data") else "other",
            "data": MessageToDict(artifact.parts[0].data),
            "name": artifact.name,
        }
    raise AssertionError(f"Unexpected A2A payload: {event_type}")


async def _collect_stream(base_url: str) -> list[dict[str, Any]]:
    client, http_client = await _create_client(base_url)
    try:
        request = SendMessageRequest(
            message=new_text_message(
                '{"question":"PostgreSQL or MongoDB?"}',
                media_type="application/json",
                role=Role.ROLE_USER,
            )
        )
        return [_project_event(response) async for response in client.send_message(request)]
    finally:
        await client.close()
        if not http_client.is_closed:
            await http_client.aclose()


async def _cancel_after_working(base_url: str) -> tuple[list[dict[str, Any]], Task]:
    stream_client, stream_http = await _create_client(base_url)
    cancel_client, cancel_http = await _create_client(base_url)
    try:
        request = SendMessageRequest(
            message=new_text_message(
                '{"question":"PostgreSQL or MongoDB?"}',
                media_type="application/json",
                role=Role.ROLE_USER,
            )
        )
        events: list[dict[str, Any]] = []
        task_id: str | None = None
        cancelled_task: Task | None = None
        async for response in stream_client.send_message(request):
            projected = _project_event(response)
            events.append(projected)
            task_id = projected.get("task_id", task_id)
            if projected.get("state") == "TASK_STATE_WORKING" and cancelled_task is None:
                if task_id is None:
                    raise AssertionError("The adapter stream did not expose a task ID.")
                cancelled_task = await cancel_client.cancel_task(CancelTaskRequest(id=task_id))
        if cancelled_task is None:
            raise AssertionError("The adapter completed before cancellation was requested.")
        return events, cancelled_task
    finally:
        await stream_client.close()
        await cancel_client.close()
        if not stream_http.is_closed:
            await stream_http.aclose()
        if not cancel_http.is_closed:
            await cancel_http.aclose()


def test_native_bridge_exposes_jsonrpc_not_agentdesk_http_json() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from agentdesk_scoper.native_bridge import app as native_app

    assert any("[EXPERIMENTAL]" in str(item.message) for item in caught)
    response, routes = asyncio.run(_read_native_card(native_app))

    assert response.status_code == 200
    interface = response.json()["supportedInterfaces"][0]
    assert interface["protocolBinding"] == TransportProtocol.JSONRPC
    assert interface["protocolBinding"] != TransportProtocol.HTTP_JSON
    assert interface["protocolVersion"] == "1.0"
    assert any(route.path == "/" and "POST" in route.methods for route in routes)


def test_adapter_card_and_stream_match_agentdesk_conventions() -> None:
    with _running_adapter() as base_url:
        card = httpx.get(f"{base_url}/.well-known/agent-card.json").json()
        events = asyncio.run(_collect_stream(base_url))

    assert card["supportedInterfaces"] == [
        {
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
            "url": base_url,
        }
    ]
    assert [skill["id"] for skill in card["skills"]] == ["decision-scoping"]
    assert [event["kind"] for event in events] == [
        "task",
        "status",
        "artifact",
        "status",
    ]
    artifact = next(event for event in events if event["kind"] == "artifact")
    assert artifact["part_kind"] == "data"
    assert artifact["name"] == "scope-proposal"
    assert artifact["data"] == SCOPE_FIXTURE
    assert events[-1]["state"] == "TASK_STATE_COMPLETED"


@pytest.mark.parametrize(
    ("delay_seconds", "malformed_output", "timeout_seconds", "message"),
    [
        (0.0, True, 2.0, "Decision scoping returned an invalid artifact."),
        (1.0, False, 0.1, "Decision scoping timed out."),
    ],
)
def test_adapter_rejects_malformed_output_and_bounds_execution(
    delay_seconds: float,
    malformed_output: bool,
    timeout_seconds: float,
    message: str,
) -> None:
    with _running_adapter(
        delay_seconds=delay_seconds,
        malformed_output=malformed_output,
        timeout_seconds=timeout_seconds,
    ) as base_url:
        events = asyncio.run(_collect_stream(base_url))

    assert events[-1]["kind"] == "status"
    assert events[-1]["state"] == "TASK_STATE_FAILED"
    assert events[-1]["text"] == message
    assert not any(event["kind"] == "artifact" for event in events)


def test_adapter_cancels_active_adk_execution_without_an_artifact() -> None:
    with _running_adapter(delay_seconds=5.0) as base_url:
        events, cancelled_task = asyncio.run(_cancel_after_working(base_url))

    assert cancelled_task.status.state == TaskState.TASK_STATE_CANCELED
    assert events[-1]["kind"] == "status"
    assert events[-1]["state"] == "TASK_STATE_CANCELED"
    assert events[-1]["text"] == "Decision scoping cancelled."
    assert not any(event["kind"] == "artifact" for event in events)
