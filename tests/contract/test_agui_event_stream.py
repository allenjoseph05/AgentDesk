"""Cross-language contract for the Coordinator's official AG-UI event stream."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from ag_ui.core import (
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder

from packages.contracts import AgentDeskViewState

pytestmark = pytest.mark.agui_contract

ROOT = Path(__file__).resolve().parents[2]
STREAM_FIXTURE = ROOT / "fixtures" / "agui" / "official-python-stream.sse"
MALFORMED_FIXTURE = ROOT / "fixtures" / "agui" / "malformed-events.json"
TERMINAL_EVENTS = {"RUN_FINISHED", "RUN_ERROR"}


def _snapshot() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "sessionId": "run-python-contract",
        "question": "PostgreSQL or MongoDB?",
        "status": "planning",
        "activeStep": "plan",
        "agents": [],
        "evidence": [],
        "evidenceCount": 0,
        "claims": [],
        "analysis": None,
        "recommendationChallenge": None,
        "verification": None,
        "warnings": [],
        "errors": [],
        "availableActions": [],
        "lastUpdatedAt": "2026-08-23T09:00:00Z",
    }


def _delta() -> list[dict[str, object]]:
    return [
        {"op": "replace", "path": "/status", "value": "partial"},
        {"op": "replace", "path": "/activeStep", "value": None},
        {
            "op": "replace",
            "path": "/warnings",
            "value": ["Verifier unavailable; partial result retained."],
        },
        {
            "op": "replace",
            "path": "/lastUpdatedAt",
            "value": "2026-08-23T09:00:01Z",
        },
    ]


def _official_events() -> list[object]:
    return [
        RunStartedEvent(
            thread_id="thread-python-contract",
            run_id="run-python-contract",
        ),
        StepStartedEvent(step_name="plan"),
        StateSnapshotEvent(snapshot=_snapshot()),
        StateDeltaEvent(delta=_delta()),
        TextMessageStartEvent(
            message_id="assistant-python-contract",
            role="assistant",
        ),
        TextMessageContentEvent(
            message_id="assistant-python-contract",
            delta="Partial result retained.",
        ),
        TextMessageEndEvent(message_id="assistant-python-contract"),
        StepFinishedEvent(step_name="plan"),
        RunFinishedEvent(
            thread_id="thread-python-contract",
            run_id="run-python-contract",
            result={"status": "partial"},
        ),
    ]


def _decode_sse(stream: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in stream.strip().split("\n\n"):
        assert block.startswith("data: ")
        event = json.loads(block.removeprefix("data: "))
        assert isinstance(event, dict)
        events.append(event)
    return events


def _assert_stream_contract(events: list[dict[str, Any]]) -> None:
    assert events and events[0]["type"] == "RUN_STARTED"
    terminals = [event for event in events if event["type"] in TERMINAL_EVENTS]
    assert len(terminals) == 1
    assert events[-1] == terminals[0]

    snapshot_indices = [
        index for index, event in enumerate(events) if event["type"] == "STATE_SNAPSHOT"
    ]
    assert len(snapshot_indices) == 1
    assert all(
        snapshot_indices[0] < index
        for index, event in enumerate(events)
        if event["type"] == "STATE_DELTA"
    )

    active_messages: set[str] = set()
    active_steps: set[str] = set()
    for event in events:
        event_type = event["type"]
        if event_type == "TEXT_MESSAGE_START":
            message_id = event["messageId"]
            assert message_id not in active_messages
            active_messages.add(message_id)
        elif event_type == "TEXT_MESSAGE_CONTENT":
            assert event["messageId"] in active_messages
        elif event_type == "TEXT_MESSAGE_END":
            active_messages.remove(event["messageId"])
        elif event_type == "STEP_STARTED":
            step_name = event["stepName"]
            assert step_name not in active_steps
            active_steps.add(step_name)
        elif event_type == "STEP_FINISHED":
            active_steps.remove(event["stepName"])
    assert not active_messages
    assert not active_steps


def _apply_top_level_delta(snapshot: dict[str, Any], delta: list[dict[str, Any]]) -> dict[str, Any]:
    candidate = deepcopy(snapshot)
    for operation in delta:
        assert operation["op"] == "replace"
        path = operation["path"]
        assert isinstance(path, str) and path.startswith("/") and "/" not in path[1:]
        candidate[path[1:]] = deepcopy(operation["value"])
    return candidate


def test_shared_stream_is_exact_official_python_encoding() -> None:
    encoder = EventEncoder(accept="text/event-stream")
    expected = "".join(encoder.encode(event) for event in _official_events())

    assert STREAM_FIXTURE.read_text(encoding="utf-8").rstrip("\n") == expected.rstrip("\n")


def test_stream_order_ids_and_snapshot_delta_equivalence() -> None:
    events = _decode_sse(STREAM_FIXTURE.read_text(encoding="utf-8"))

    _assert_stream_contract(events)
    snapshot = next(event["snapshot"] for event in events if event["type"] == "STATE_SNAPSHOT")
    deltas = [event["delta"] for event in events if event["type"] == "STATE_DELTA"]
    final_state = snapshot
    for delta in deltas:
        final_state = _apply_top_level_delta(final_state, delta)

    validated = AgentDeskViewState.model_validate(final_state)
    assert validated.status == "partial"
    assert validated.active_step is None
    assert validated.warnings == ["Verifier unavailable; partial result retained."]


def test_malformed_event_fixture_exercises_each_protocol_failure() -> None:
    fixture = json.loads(MALFORMED_FIXTURE.read_text(encoding="utf-8"))

    assert {case["caseId"] for case in fixture["cases"]} == {
        "missing-run-start",
        "text-content-without-start",
        "step-finish-without-start",
        "event-after-run-error",
        "event-after-run-finished",
    }
