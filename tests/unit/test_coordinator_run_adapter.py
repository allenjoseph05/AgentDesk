"""Production Coordinator AG-UI run adapter tests."""

from __future__ import annotations

import ast
import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder

from agents.coordinator.run_adapter import (
    ChallengeRecommendationCommand,
    CoordinatorCommand,
    CoordinatorRunAdapter,
    CoordinatorRunOutcome,
    FocusOnCriterionCommand,
    RemoteTaskCorrelation,
    ResearchDeeperCommand,
    RetryFailedAgentCommand,
    StartResearchCommand,
)

ROOT = Path(__file__).resolve().parents[2]


def _start_action(
    *,
    action_id: str = "action-start",
    question: str = "Should we use PostgreSQL or MongoDB?",
) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "actionId": action_id,
        "type": "start_research",
        "sessionId": None,
        "payload": {
            "question": question,
            "options": ["PostgreSQL", "MongoDB"],
            "constraints": ["Preserve transactions"],
            "criteria": ["Data integrity"],
            "desiredDepth": "normal",
        },
    }


def _state(session_id: str = "session-1") -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "sessionId": session_id,
        "question": "Should we use PostgreSQL or MongoDB?",
        "status": "completed",
        "activeStep": None,
        "agents": [],
        "evidence": [],
        "evidenceCount": 0,
        "claims": [],
        "analysis": None,
        "verification": None,
        "warnings": [],
        "errors": [],
        "availableActions": [],
        "lastUpdatedAt": "2026-08-17T12:00:00Z",
    }


def _input(
    action: dict[str, Any],
    message: str,
    *,
    run_id: str = "run-1",
    state: dict[str, Any] | None = None,
) -> RunAgentInput:
    return RunAgentInput.model_validate(
        {
            "threadId": "thread-1",
            "runId": run_id,
            "state": state or {},
            "messages": [
                {"id": "message-1", "role": "user", "content": message}
            ],
            "tools": [],
            "context": [],
            "forwardedProps": {"agentdesk": action},
        }
    )


async def _events(
    adapter: CoordinatorRunAdapter,
    input_data: RunAgentInput,
) -> list[dict[str, Any]]:
    return [
        json.loads(item.removeprefix("data: "))
        async for item in adapter.stream(
            input_data,
            EventEncoder(accept="text/event-stream"),
        )
    ]


class RecordingExecutor:
    def __init__(self, outcome: CoordinatorRunOutcome | None = None) -> None:
        self.outcome = outcome or CoordinatorRunOutcome(status="completed")
        self.commands: list[CoordinatorCommand] = []

    async def execute(
        self, command: CoordinatorCommand
    ) -> AsyncIterator[CoordinatorRunOutcome]:
        self.commands.append(command)
        yield self.outcome


@pytest.mark.parametrize(
    ("action", "message", "command_type", "expected"),
    [
        (
            _start_action(),
            "Should we use PostgreSQL or MongoDB?",
            StartResearchCommand,
            ("normal",),
        ),
        (
            {
                "schemaVersion": "1.0",
                "actionId": "action-challenge",
                "type": "challenge_recommendation",
                "sessionId": "session-1",
                "payload": {"challenge": "Make the strongest opposing case."},
            },
            "Make the strongest opposing case.",
            ChallengeRecommendationCommand,
            ("Make the strongest opposing case.",),
        ),
        (
            {
                "schemaVersion": "1.0",
                "actionId": "action-deeper",
                "type": "research_deeper",
                "sessionId": "session-1",
                "payload": {"focusAreas": ["Cost"], "desiredDepth": "deep"},
            },
            "Research cost more deeply.",
            ResearchDeeperCommand,
            (("Cost",), "deep"),
        ),
        (
            {
                "schemaVersion": "1.0",
                "actionId": "action-focus",
                "type": "focus_on_criterion",
                "sessionId": "session-1",
                "payload": {"criterion": "Operational complexity"},
            },
            "Focus on operational complexity.",
            FocusOnCriterionCommand,
            ("Operational complexity",),
        ),
        (
            {
                "schemaVersion": "1.0",
                "actionId": "action-retry",
                "type": "retry_failed_agent",
                "sessionId": "session-1",
                "payload": {"agentId": "researcher", "remoteTaskId": "task-old"},
            },
            "Retry the failed research agent.",
            RetryFailedAgentCommand,
            ("researcher", "task-old"),
        ),
    ],
)
def test_strict_actions_map_to_typed_coordinator_commands(
    action: dict[str, Any],
    message: str,
    command_type: type[CoordinatorCommand],
    expected: tuple[Any, ...],
) -> None:
    async def scenario() -> CoordinatorCommand:
        executor = RecordingExecutor()
        adapter = CoordinatorRunAdapter(executor=executor)
        state = None if action["type"] == "start_research" else _state()
        events = await _events(adapter, _input(action, message, state=state))
        assert events[-1]["type"] == "RUN_FINISHED"
        return executor.commands[0]

    command = asyncio.run(scenario())

    assert isinstance(command, command_type)
    assert command.correlation.thread_id == "thread-1"
    assert command.correlation.run_id == "run-1"
    if isinstance(command, StartResearchCommand):
        assert (command.request.desired_depth,) == expected
    elif isinstance(command, ChallengeRecommendationCommand):
        assert (command.challenge,) == expected
    elif isinstance(command, ResearchDeeperCommand):
        assert (command.focus_areas, command.desired_depth) == expected
    elif isinstance(command, FocusOnCriterionCommand):
        assert (command.criterion,) == expected
    else:
        assert (command.agent_id, command.remote_task_id) == expected


def test_initial_snapshot_is_emitted_before_executor_delegation() -> None:
    async def scenario() -> None:
        executor = RecordingExecutor()
        adapter = CoordinatorRunAdapter(executor=executor)
        stream = adapter.stream(
            _input(
                _start_action(),
                "Should we use PostgreSQL or MongoDB?",
            ),
            EventEncoder(accept="text/event-stream"),
        )

        first_three = [
            json.loads((await anext(stream)).removeprefix("data: "))
            for _ in range(3)
        ]
        assert [event["type"] for event in first_three] == [
            "RUN_STARTED",
            "STEP_STARTED",
            "STATE_SNAPSHOT",
        ]
        assert executor.commands == []
        remaining = [json.loads(item.removeprefix("data: ")) async for item in stream]
        assert executor.commands
        assert remaining[-1]["type"] == "RUN_FINISHED"

    asyncio.run(scenario())


def test_run_result_correlates_browser_session_and_remote_a2a_ids() -> None:
    outcome = CoordinatorRunOutcome(
        status="partial",
        remote_tasks=(
            RemoteTaskCorrelation(
                agent_id="researcher",
                remote_task_id="research-task-42",
                a2a_context_id="a2a-context-42",
            ),
        ),
    )
    adapter = CoordinatorRunAdapter(executor=RecordingExecutor(outcome))

    events = asyncio.run(
        _events(
            adapter,
            _input(
                _start_action(),
                "Should we use PostgreSQL or MongoDB?",
            ),
        )
    )

    assert events[-1]["result"] == {
        "threadId": "thread-1",
        "runId": "run-1",
        "sessionId": "run-1",
        "actionId": "action-start",
        "status": "partial",
        "remoteTasks": [
            {
                "agentId": "researcher",
                "remoteTaskId": "research-task-42",
                "a2aContextId": "a2a-context-42",
            }
        ],
    }


def test_duplicate_action_id_cannot_delegate_twice() -> None:
    async def scenario() -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        executor = RecordingExecutor()
        adapter = CoordinatorRunAdapter(executor=executor)
        first, duplicate = await asyncio.gather(
            _events(
                adapter,
                _input(
                    _start_action(),
                    "Should we use PostgreSQL or MongoDB?",
                ),
            ),
            _events(
                adapter,
                _input(
                    _start_action(),
                    "Should we use PostgreSQL or MongoDB?",
                    run_id="run-retry",
                ),
            ),
        )
        return first, duplicate, len(executor.commands)

    first, duplicate, command_count = asyncio.run(scenario())

    runs = [first, duplicate]
    assert sorted(run[-1]["type"] for run in runs) == ["RUN_ERROR", "RUN_FINISHED"]
    rejected = next(run for run in runs if run[-1]["type"] == "RUN_ERROR")
    assert [event["type"] for event in rejected] == ["RUN_STARTED", "RUN_ERROR"]
    assert rejected[-1]["code"] == "duplicate_action"
    assert command_count == 1


def test_conflicting_reuse_of_action_id_fails_closed() -> None:
    async def scenario() -> tuple[list[dict[str, Any]], int]:
        executor = RecordingExecutor()
        adapter = CoordinatorRunAdapter(executor=executor)
        await _events(
            adapter,
            _input(
                _start_action(),
                "Should we use PostgreSQL or MongoDB?",
            ),
        )
        conflict_question = "Should we use SQLite or PostgreSQL?"
        conflict = await _events(
            adapter,
            _input(
                _start_action(question=conflict_question),
                conflict_question,
                run_id="run-conflict",
            ),
        )
        return conflict, len(executor.commands)

    conflict, command_count = asyncio.run(scenario())

    assert conflict[-1]["type"] == "RUN_ERROR"
    assert conflict[-1]["code"] == "duplicate_action_conflict"
    assert command_count == 1


def test_failed_outcome_maps_to_exactly_one_run_error() -> None:
    adapter = CoordinatorRunAdapter(
        executor=RecordingExecutor(
            CoordinatorRunOutcome(
                status="failed",
                message="Planning could not select a provider.",
                error_code="planning_failed",
            )
        )
    )

    events = asyncio.run(
        _events(
            adapter,
            _input(
                _start_action(),
                "Should we use PostgreSQL or MongoDB?",
            ),
        )
    )

    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "planning_failed"
    assert sum(event["type"] in {"RUN_FINISHED", "RUN_ERROR"} for event in events) == 1


def test_cancelled_domain_outcome_maps_to_run_finished() -> None:
    adapter = CoordinatorRunAdapter(
        executor=RecordingExecutor(CoordinatorRunOutcome(status="cancelled"))
    )

    events = asyncio.run(
        _events(
            adapter,
            _input(
                _start_action(),
                "Should we use PostgreSQL or MongoDB?",
            ),
        )
    )

    assert events[-1]["type"] == "RUN_FINISHED"
    assert events[-1]["result"]["status"] == "cancelled"
    assert sum(event["type"] in {"RUN_FINISHED", "RUN_ERROR"} for event in events) == 1


def test_follow_up_session_mismatch_is_rejected_before_delegation() -> None:
    action = {
        "schemaVersion": "1.0",
        "actionId": "action-mismatch",
        "type": "focus_on_criterion",
        "sessionId": "session-1",
        "payload": {"criterion": "Cost"},
    }
    executor = RecordingExecutor()

    events = asyncio.run(
        _events(
            CoordinatorRunAdapter(executor=executor),
            _input(action, "Focus on cost.", state=_state("another-session")),
        )
    )

    assert [event["type"] for event in events] == ["RUN_STARTED", "RUN_ERROR"]
    assert events[-1]["code"] == "invalid_session_state"
    assert executor.commands == []


def test_run_adapter_has_no_specialist_implementation_imports() -> None:
    tree = ast.parse(
        (ROOT / "agents" / "coordinator" / "run_adapter.py").read_text(encoding="utf-8")
    )
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(
        module.startswith(("agents.researcher", "agents.analyst"))
        for module in imported_modules
    )
