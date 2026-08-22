"""Process-level A2A coverage for the configured Analyst Agent."""

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

from packages.contracts import (
    AnalysisRequest,
    ArtifactEnvelope,
    DecisionAnalysis,
    RecommendationChallenge,
)
from packages.testing import load_research_fixture

ROOT = Path(__file__).resolve().parents[2]


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def _running_analyst_agent(
    fixture_id: str,
    *,
    analysis_delay_seconds: float = 0,
) -> Iterator[str]:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["ANALYST_AGENT_URL"] = base_url
    environment["ANALYST_FIXTURE_ID"] = fixture_id
    environment["ANALYST_FIXTURE_DELAY_SECONDS"] = str(analysis_delay_seconds)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "agents.analyst.fixture_app:app",
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
                    f"Analyst Agent stopped early.\nstdout: {stdout}\nstderr: {stderr}"
                )
            try:
                if httpx.get(f"{base_url}/health", timeout=0.25).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("Analyst Agent did not become ready within 10 seconds.")
        yield base_url
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def _analysis_request(fixture_id: str, *, challenge: bool = False) -> AnalysisRequest:
    fixture = load_research_fixture(fixture_id)
    if fixture.evidence_bundle is None:
        raise AssertionError("Analyst integration fixture requires evidence.")
    current_recommendation = None
    if challenge:
        if fixture.decision_analysis is None:
            raise AssertionError("Challenge fixture requires an existing analysis.")
        current_recommendation = fixture.decision_analysis.recommendation
    return AnalysisRequest(
        question=fixture.request.question,
        options=fixture.request.options,
        constraints=fixture.request.constraints,
        criteria=fixture.request.criteria,
        evidence_bundle=fixture.evidence_bundle,
        mode="challenge_current_recommendation" if challenge else "compare_options",
        current_recommendation=current_recommendation,
    )


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
            "name": artifact.name,
            "data": MessageToDict(artifact.parts[0].data),
            "metadata": MessageToDict(artifact.metadata),
            "last_chunk": response.artifact_update.last_chunk,
        }
    raise AssertionError(f"Unexpected A2A payload: {event_type}")


async def _create_client(base_url: str, http_client: httpx.AsyncClient):
    return await ClientFactory(
        ClientConfig(
            streaming=True,
            httpx_client=http_client,
            supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
        )
    ).create_from_url(base_url)


async def _collect_stream(base_url: str, payload: str) -> list[dict[str, Any]]:
    http_client = httpx.AsyncClient(timeout=10.0)
    client = None
    try:
        client = await _create_client(base_url, http_client)
        request = SendMessageRequest(
            message=new_text_message(
                payload,
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


async def _cancel_after_working(
    base_url: str,
    request_payload: str,
) -> tuple[list[dict[str, Any]], Task]:
    stream_http = httpx.AsyncClient(timeout=10.0)
    cancel_http = httpx.AsyncClient(timeout=10.0)
    stream_client = None
    cancel_client = None
    try:
        stream_client = await _create_client(base_url, stream_http)
        cancel_client = await _create_client(base_url, cancel_http)
        request = SendMessageRequest(
            message=new_text_message(
                request_payload,
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
                    raise AssertionError("Analyst stream did not expose a task ID.")
                cancelled_task = await cancel_client.cancel_task(CancelTaskRequest(id=task_id))

        if cancelled_task is None:
            raise AssertionError("Analysis completed before cancellation was requested.")
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


def test_agent_card_and_happy_path_analysis_across_process_boundary() -> None:
    fixture_id = "postgresql-vs-mongodb-golden"
    request = _analysis_request(fixture_id)
    with _running_analyst_agent(fixture_id) as base_url:
        card = httpx.get(f"{base_url}/.well-known/agent-card.json").json()
        events = asyncio.run(_collect_stream(base_url, request.model_dump_json()))

    assert card["name"] == "AgentDesk Analyst Agent"
    assert card["supportedInterfaces"][0]["url"] == base_url
    assert card["capabilities"]["streaming"] is True
    assert [skill["id"] for skill in card["skills"]] == ["decision-analysis"]
    assert [event["kind"] for event in events] == ["task", "status", "artifact", "status"]
    assert [event["state"] for event in events if event["kind"] == "status"] == [
        "TASK_STATE_WORKING",
        "TASK_STATE_COMPLETED",
    ]
    artifact = next(event for event in events if event["kind"] == "artifact")
    assert artifact["name"] == "decision-analysis"
    envelope = ArtifactEnvelope[DecisionAnalysis].model_validate(artifact["data"])
    assert envelope.payload == load_research_fixture(fixture_id).decision_analysis
    assert envelope.provenance.remote_task_id == events[0]["task_id"]


def test_partial_evidence_produces_an_explicitly_cautious_analysis() -> None:
    fixture_id = "postgresql-vs-mongodb-partial"
    request = _analysis_request(fixture_id)
    with _running_analyst_agent(fixture_id) as base_url:
        events = asyncio.run(_collect_stream(base_url, request.model_dump_json()))

    artifact = next(event for event in events if event["kind"] == "artifact")
    analysis = ArtifactEnvelope[DecisionAnalysis].model_validate(artifact["data"]).payload
    caution_text = " ".join(
        [
            analysis.executive_summary,
            *analysis.arguments_against,
            *analysis.assumptions,
            *analysis.risks,
            *analysis.recommendation_changes_if,
        ]
    ).casefold()
    assert "provisional" in caution_text
    assert "unavailable" in caution_text
    assert "missing" in caution_text
    assert {claim_id for item in analysis.criteria for claim_id in item.supporting_claim_ids} == {
        "claim-partial"
    }


def test_invalid_evidence_input_is_rejected_over_a2a() -> None:
    fixture_id = "postgresql-vs-mongodb-golden"
    malformed = '{"question":"Compare databases","evidence_bundle":{}}'
    with _running_analyst_agent(fixture_id) as base_url:
        events = asyncio.run(_collect_stream(base_url, malformed))

    assert [event["kind"] for event in events] == ["task", "status"]
    assert events[-1]["state"] == "TASK_STATE_REJECTED"
    assert "AnalysisRequest schema" in events[-1]["text"]
    assert not any(event["kind"] == "artifact" for event in events)


def test_challenge_mode_returns_a_separate_artifact_over_a2a() -> None:
    fixture_id = "postgresql-vs-mongodb-golden"
    request = _analysis_request(fixture_id, challenge=True)
    with _running_analyst_agent(fixture_id) as base_url:
        events = asyncio.run(_collect_stream(base_url, request.model_dump_json()))

    artifact = next(event for event in events if event["kind"] == "artifact")
    assert artifact["name"] == "recommendation-challenge"
    challenge = ArtifactEnvelope[RecommendationChallenge].model_validate(artifact["data"]).payload
    assert challenge.current_recommendation == "PostgreSQL"
    assert challenge.strongest_alternative == "MongoDB"
    assert events[-1]["state"] == "TASK_STATE_COMPLETED"


def test_official_cancel_path_stops_active_analysis() -> None:
    fixture_id = "postgresql-vs-mongodb-golden"
    request = _analysis_request(fixture_id)
    with _running_analyst_agent(fixture_id, analysis_delay_seconds=5) as base_url:
        events, cancelled_task = asyncio.run(
            _cancel_after_working(base_url, request.model_dump_json())
        )

    assert cancelled_task.status.state == TaskState.TASK_STATE_CANCELED
    assert events[-1]["kind"] == "status"
    assert events[-1]["state"] == "TASK_STATE_CANCELED"
    assert events[-1]["text"] == "Analysis task cancelled."
    assert not any(event["kind"] == "artifact" for event in events)
