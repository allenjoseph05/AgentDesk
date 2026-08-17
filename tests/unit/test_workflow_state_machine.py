"""Transition graph and invariant tests for Coordinator workflow state."""

from datetime import UTC, datetime, timedelta

import pytest

from agents.coordinator.workflow_state import (
    LEGAL_TRANSITIONS,
    TERMINAL_STATUSES,
    InvalidWorkflowTransition,
    WorkflowStateMachine,
)


class AdvancingClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def test_happy_path_uses_only_explicit_transitions_and_records_history() -> None:
    machine = WorkflowStateMachine("session-1", clock=AdvancingClock())

    machine.transition("planning", active_step="create-plan")
    machine.transition(
        "researching",
        active_step="research",
        completed_steps=["create-plan"],
    )
    machine.transition(
        "analyzing",
        active_step="analysis",
        completed_steps=["research"],
    )
    final = machine.transition("completed", completed_steps=["analysis"])

    assert final.status == "completed"
    assert final.active_step is None
    assert final.completed_steps == ["create-plan", "research", "analysis"]
    assert final.failed_steps == []
    assert [item.sequence for item in machine.history] == [1, 2, 3, 4]
    assert [(item.from_status, item.to_status) for item in machine.history] == [
        ("created", "planning"),
        ("planning", "researching"),
        ("researching", "analyzing"),
        ("analyzing", "completed"),
    ]


def test_every_terminal_status_has_no_outgoing_transition() -> None:
    assert TERMINAL_STATUSES == {"completed", "partial", "failed", "cancelled"}
    assert all(LEGAL_TRANSITIONS[status] == frozenset() for status in TERMINAL_STATUSES)


@pytest.mark.parametrize("terminal", ["completed", "partial", "failed", "cancelled"])
def test_terminal_state_cannot_transition_back_to_working(terminal: str) -> None:
    machine = WorkflowStateMachine("session-terminal")
    machine.transition("planning", active_step="plan")
    if terminal == "completed":
        machine.transition("researching", active_step="research")
        machine.transition("analyzing", active_step="analysis")
        machine.transition("completed", completed_steps=["research", "analysis"])
    elif terminal == "partial":
        machine.transition("researching", active_step="research")
        machine.transition(
            "partial",
            completed_steps=["research"],
            failed_steps=["analysis"],
            reason="Analysis provider timed out.",
        )
    elif terminal == "failed":
        machine.transition("failed", failed_steps=["planning"], reason="Planning failed.")
    else:
        machine.transition("cancelling", active_step="cancel-remote-work")
        machine.transition("cancelled", reason="Cancelled by the user.")

    with pytest.raises(InvalidWorkflowTransition, match="cannot transition"):
        machine.transition("researching", active_step="research-again")


def test_partial_completion_requires_both_success_and_failure() -> None:
    machine = WorkflowStateMachine("session-partial")
    machine.transition("planning", active_step="plan")
    machine.transition("researching", active_step="research")

    with pytest.raises(InvalidWorkflowTransition, match="completed and failed"):
        machine.transition(
            "partial",
            completed_steps=["research"],
            reason="Analysis did not complete.",
        )

    assert machine.snapshot.status == "researching"
    assert len(machine.history) == 2

    partial = machine.transition(
        "partial",
        completed_steps=["research"],
        failed_steps=["analysis"],
        reason="Analysis provider timed out.",
    )
    assert partial.status == "partial"
    assert partial.completed_steps == ["research"]
    assert partial.failed_steps == ["analysis"]


def test_illegal_jump_and_missing_active_step_do_not_mutate_state() -> None:
    machine = WorkflowStateMachine("session-guarded")

    with pytest.raises(InvalidWorkflowTransition):
        machine.transition("researching", active_step="research")
    with pytest.raises(InvalidWorkflowTransition, match="active step"):
        machine.transition("planning")

    assert machine.snapshot.status == "created"
    assert machine.history == ()


def test_step_cannot_be_recorded_as_both_completed_and_failed() -> None:
    machine = WorkflowStateMachine("session-overlap")
    machine.transition("planning", active_step="plan")
    machine.transition("researching", active_step="research", completed_steps=["plan"])

    with pytest.raises(InvalidWorkflowTransition, match="both succeed and fail"):
        machine.transition(
            "partial",
            completed_steps=["research"],
            failed_steps=["research"],
            reason="Conflicting event projection.",
        )


def test_returned_snapshots_and_history_cannot_mutate_machine_state() -> None:
    machine = WorkflowStateMachine("session-copy")
    snapshot = machine.transition("planning", active_step="plan")
    history = machine.history

    snapshot.completed_steps.append("injected")
    history[0].reason = "mutated outside"

    assert machine.snapshot.completed_steps == []
    assert machine.history[0].reason is None
