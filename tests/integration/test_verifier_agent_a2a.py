"""Process-level A2A contract coverage for the configured Verifier Agent."""

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
import pytest
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.types import Role, SendMessageRequest, TaskState
from a2a.utils.constants import TransportProtocol
from google.protobuf.json_format import MessageToDict

from packages.contracts import ArtifactEnvelope, VerificationReport
from packages.testing import load_research_fixture

pytestmark = pytest.mark.a2a_contract
ROOT = Path(__file__).resolve().parents[2]


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def _running_verifier_agent(fixture_id: str) -> Iterator[str]:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["VERIFIER_AGENT_URL"] = base_url
    environment["VERIFIER_FIXTURE_ID"] = fixture_id
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "agents.verifier.fixture_app:app",
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
                    f"Verifier Agent stopped early.\nstdout: {stdout}\nstderr: {stderr}"
                )
            try:
                if httpx.get(f"{base_url}/health", timeout=0.25).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("Verifier Agent did not become ready within 10 seconds.")
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
            "context_id": response.task.context_id,
            "state": TaskState.Name(response.task.status.state),
        }
    if event_type == "status_update":
        status = response.status_update.status
        return {
            "kind": "status",
            "task_id": response.status_update.task_id,
            "context_id": response.status_update.context_id,
            "state": TaskState.Name(status.state),
            "text": get_message_text(status.message) if status.HasField("message") else "",
        }
    if event_type == "artifact_update":
        update = response.artifact_update
        artifact = update.artifact
        return {
            "kind": "artifact",
            "task_id": update.task_id,
            "context_id": update.context_id,
            "name": artifact.name,
            "data": MessageToDict(artifact.parts[0].data),
            "last_chunk": update.last_chunk,
        }
    raise AssertionError(f"Unexpected A2A payload: {event_type}")


async def _collect_stream(base_url: str, fixture_id: str) -> list[dict[str, Any]]:
    fixture = load_research_fixture(fixture_id)
    assert fixture.evidence_bundle is not None
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
                fixture.evidence_bundle.model_dump_json(),
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


def test_agent_card_and_verification_stream_preserve_task_context() -> None:
    fixture_id = "postgresql-vs-mongodb-golden"
    fixture = load_research_fixture(fixture_id)
    assert fixture.verification_report is not None
    with _running_verifier_agent(fixture_id) as base_url:
        card = httpx.get(f"{base_url}/.well-known/agent-card.json").json()
        events = asyncio.run(_collect_stream(base_url, fixture_id))

    assert card["name"] == "AgentDesk Verifier Agent"
    assert card["supportedInterfaces"][0]["url"] == base_url
    assert {skill["id"] for skill in card["skills"]} == {"fact-verification"}
    assert [event["kind"] for event in events] == [
        "task",
        "status",
        "artifact",
        "status",
    ]
    assert events[-1]["state"] == "TASK_STATE_COMPLETED"
    assert {event["task_id"] for event in events} == {events[0]["task_id"]}
    assert {event["context_id"] for event in events} == {events[0]["context_id"]}
    artifact = next(event for event in events if event["kind"] == "artifact")
    assert artifact["name"] == "verification-report"
    assert artifact["last_chunk"] is True
    envelope = ArtifactEnvelope[VerificationReport].model_validate(artifact["data"])
    assert envelope.provenance.remote_task_id == events[0]["task_id"]
    assert envelope.payload == fixture.verification_report
