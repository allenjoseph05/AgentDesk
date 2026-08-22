"""Safe structured logging and correlation-scope tests."""

from __future__ import annotations

import json
import logging

import pytest

from packages.observability import (
    CorrelationIds,
    correlation_scope,
    log_event,
    observed_request,
)

LOGGER = logging.getLogger("agents.tests.structured_logging")


def _events(caplog: pytest.LogCaptureFixture) -> list[dict[str, str | None]]:
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == LOGGER.name
    ]


def test_log_event_emits_fixed_schema_and_inherited_correlation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)

    with correlation_scope(
        CorrelationIds(
            session_id="session-1",
            context_id="browser-context-1",
            correlation_id="run-1",
            action_id="action-1",
            agent="coordinator",
        )
    ):
        log_event(
            LOGGER,
            "a2a.remote_task",
            ids=CorrelationIds(
                context_id="a2a-context-1",
                agent="researcher",
                remote_task_id="task-1",
            ),
            outcome="completed",
        )

    event = _events(caplog)[0]
    assert event == {
        "action_id": "action-1",
        "agent": "researcher",
        "context_id": "a2a-context-1",
        "correlation_id": "run-1",
        "error_code": None,
        "event": "a2a.remote_task",
        "level": "info",
        "outcome": "completed",
        "remote_task_id": "task-1",
        "session_id": "session-1",
        "span_id": None,
        "timestamp": event["timestamp"],
        "trace_id": None,
    }


def test_request_failure_does_not_log_exception_headers_or_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    secret = "Authorization: Bearer should-never-appear"

    with pytest.raises(RuntimeError, match="should-never-appear"):
        with observed_request(
            LOGGER,
            "a2a.request",
            CorrelationIds(context_id="context-1", agent="researcher"),
        ):
            raise RuntimeError(secret)

    encoded = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in encoded
    assert "Bearer" not in encoded
    assert [event["outcome"] for event in _events(caplog)] == ["started", "failed"]
    assert _events(caplog)[-1]["error_code"] == "unhandled_exception"


def test_identifiers_are_bounded_and_cannot_inject_log_lines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    log_event(
        LOGGER,
        "a2a.request",
        ids=CorrelationIds(remote_task_id=f"task\nforged{('x' * 300)}"),
    )

    event = _events(caplog)[0]
    remote_task_id = event["remote_task_id"]
    assert remote_task_id is not None
    assert "\n" not in remote_task_id
    assert len(remote_task_id) == 255
