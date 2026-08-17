"""Process-level A2A coverage for the configured Research Agent."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.types import CancelTaskRequest, Role, SendMessageRequest, Task, TaskState
from a2a.utils.constants import TransportProtocol
from google.protobuf.json_format import MessageToDict

from packages.contracts import ArtifactEnvelope, EvidenceBundle
from packages.testing import load_research_fixture

ROOT = Path(__file__).resolve().parents[2]


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def _running_research_agent(
    fixture_id: str,
    *,
    search_delay_seconds: float = 0,
) -> Iterator[str]:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["RESEARCH_AGENT_URL"] = base_url
    environment["RESEARCH_FIXTURE_ID"] = fixture_id
    environment["RESEARCH_FIXTURE_SEARCH_DELAY_SECONDS"] = str(search_delay_seconds)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "agents.researcher.fixture_app:app",
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
                    f"Research Agent stopped early.\nstdout: {stdout}\nstderr: {stderr}"
                )
            try:
                if httpx.get(f"{base_url}/health", timeout=0.25).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("Research Agent did not become ready within 10 seconds.")
        yield base_url
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


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
        data = MessageToDict(artifact.parts[0].data)
        return {
            "kind": "artifact",
            "task_id": response.artifact_update.task_id,
            "name": artifact.name,
            "data": data,
            "metadata": MessageToDict(artifact.metadata),
            "last_chunk": response.artifact_update.last_chunk,
        }
    raise AssertionError(f"Unexpected A2A payload: {event_type}")


async def _collect_stream(base_url: str, fixture_id: str) -> list[dict[str, Any]]:
    fixture = load_research_fixture(fixture_id)
    http_client = httpx.AsyncClient(timeout=10.0)
    client = None
    try:
        client = await ClientFactory(
            ClientConfig(
                streaming=True,
                httpx_client=http_client,
                supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
            )
        ).create_from_url(base_url)
        request = SendMessageRequest(
            message=new_text_message(
                fixture.request.model_dump_json(),
                media_type="application/json",
                role=Role.ROLE_USER,
            )
        )
        return [_project_event(response) async for response in client.send_message(request)]
    finally:
        if client is not None:
            await client.close()
        elif not http_client.is_closed:
            await http_client.aclose()


async def _cancel_after_search_started(
    base_url: str,
    fixture_id: str,
) -> tuple[list[dict[str, Any]], Task]:
    fixture = load_research_fixture(fixture_id)
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
            message=new_text_message(
                fixture.request.model_dump_json(),
                media_type="application/json",
                role=Role.ROLE_USER,
            )
        )
        events: list[dict[str, Any]] = []
        task_id: str | None = None
        cancelled_task: Task | None = None
        async for response in stream_client.send_message(request):
            events.append(_project_event(response))
            if response.HasField("task"):
                task_id = response.task.id
            if (
                response.HasField("status_update")
                and response.status_update.status.state == TaskState.TASK_STATE_WORKING
                and cancelled_task is None
            ):
                if task_id is None:
                    raise AssertionError("Research stream did not expose a task ID.")
                cancelled_task = await cancel_client.cancel_task(CancelTaskRequest(id=task_id))

        if cancelled_task is None:
            raise AssertionError("Research completed before cancellation was requested.")
        return events, cancelled_task
    finally:
        if stream_client is not None:
            await stream_client.close()
        elif not stream_http.is_closed:
            await stream_http.aclose()
        if cancel_client is not None:
            await cancel_client.close()
        elif not cancel_http.is_closed:
            await cancel_http.aclose()


def test_agent_card_discovery_and_full_fixture_stream_across_process_boundary() -> None:
    fixture_id = "postgresql-vs-mongodb-golden"
    with _running_research_agent(fixture_id) as base_url:
        card = httpx.get(f"{base_url}/.well-known/agent-card.json").json()
        events = asyncio.run(_collect_stream(base_url, fixture_id))

    assert card["name"] == "AgentDesk Research Agent"
    assert card["supportedInterfaces"][0]["url"] == base_url
    assert card["capabilities"]["streaming"] is True
    assert card["defaultInputModes"] == ["application/json"]
    assert {skill["id"] for skill in card["skills"]} == {"web-research", "source-synthesis"}

    assert [event["kind"] for event in events] == [
        "task",
        "status",
        "status",
        "status",
        "artifact",
        "artifact",
        "status",
    ]
    assert [event["state"] for event in events if event["kind"] == "status"] == [
        "TASK_STATE_WORKING",
        "TASK_STATE_WORKING",
        "TASK_STATE_WORKING",
        "TASK_STATE_COMPLETED",
    ]
    assert [event["name"] for event in events if event["kind"] == "artifact"] == [
        "research-sources",
        "evidence-bundle",
    ]
    task_ids = {event["task_id"] for event in events}
    assert len(task_ids) == 1
    final_artifact = next(event for event in events if event.get("name") == "evidence-bundle")
    envelope = ArtifactEnvelope[EvidenceBundle].model_validate(final_artifact["data"])
    assert envelope.provenance.remote_task_id == next(iter(task_ids))
    assert envelope.payload == load_research_fixture(fixture_id).evidence_bundle


def test_tool_failure_stream_reaches_terminal_failed_state() -> None:
    fixture_id = "postgresql-vs-mongodb-failure"
    with _running_research_agent(fixture_id) as base_url:
        events = asyncio.run(_collect_stream(base_url, fixture_id))

    assert [event["kind"] for event in events] == ["task", "status", "status"]
    assert events[-1]["state"] == "TASK_STATE_FAILED"
    assert "fixture_source_unavailable" in events[-1]["text"]
    assert not any(event["kind"] == "artifact" for event in events)


def test_official_cancel_path_stops_active_research_task() -> None:
    fixture_id = "postgresql-vs-mongodb-golden"
    with _running_research_agent(fixture_id, search_delay_seconds=5) as base_url:
        events, cancelled_task = asyncio.run(_cancel_after_search_started(base_url, fixture_id))

    assert cancelled_task.status.state == TaskState.TASK_STATE_CANCELED
    assert events[-1]["kind"] == "status"
    assert events[-1]["state"] == "TASK_STATE_CANCELED"
    assert events[-1]["text"] == "Research task cancelled."
    assert not any(event["kind"] == "artifact" for event in events)
