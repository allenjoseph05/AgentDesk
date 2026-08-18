"""Coordinator cancellation propagation and race-safety tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agents.coordinator.cancellation import (
    CancellationCoordinator,
    CancellationRejectedError,
)
from agents.coordinator.registry import RegisteredAgent
from agents.coordinator.workflow_state import (
    InvalidWorkflowTransition,
    WorkflowSnapshot,
    WorkflowStateMachine,
)
from agents.researcher.agent_card import create_agent_card as create_research_card


def _agent(agent_id: str = "researcher") -> RegisteredAgent:
    base_url = f"https://{agent_id}.example"
    return RegisteredAgent(
        agent_id=agent_id,
        base_url=base_url,
        card=create_research_card(base_url),
    )


def _active_machine(session_id: str = "session-cancel") -> WorkflowStateMachine:
    machine = WorkflowStateMachine(session_id)
    machine.transition("planning", active_step="plan")
    machine.transition("researching", active_step="research")
    return machine


class RecordingCanceller:
    def __init__(self, *, failing_task_ids: set[str] | None = None) -> None:
        self.failing_task_ids = failing_task_ids or set()
        self.calls: list[tuple[str, str, float]] = []

    async def cancel(self, **kwargs: Any) -> None:
        agent = kwargs["agent"]
        task_id = kwargs["remote_task_id"]
        self.calls.append((agent.agent_id, task_id, kwargs["timeout_seconds"]))
        await asyncio.sleep(0)
        if task_id in self.failing_task_ids:
            raise RuntimeError(f"remote cancellation failed for {task_id}")


class BlockingCanceller(RecordingCanceller):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def cancel(self, **kwargs: Any) -> None:
        self.calls.append(
            (
                kwargs["agent"].agent_id,
                kwargs["remote_task_id"],
                kwargs["timeout_seconds"],
            )
        )
        self.started.set()
        await self.release.wait()


def test_cancellation_is_terminal_and_notifies_ui_projection() -> None:
    async def scenario() -> None:
        machine = _active_machine()
        canceller = RecordingCanceller()
        snapshots: list[WorkflowSnapshot] = []

        async def snapshot_changed(snapshot: WorkflowSnapshot) -> None:
            snapshots.append(snapshot)

        coordinator = CancellationCoordinator(
            state_machine=machine,
            remote_canceller=canceller,
            timeout_seconds=2,
            on_state_snapshot=snapshot_changed,
        )
        await coordinator.register(_agent(), "research-task")
        await coordinator.register(_agent("researcher-2"), "research-task-2")

        result = await coordinator.cancel("user requested cancellation")
        await coordinator.complete("research-task")

        assert result.snapshot.status == "cancelled"
        assert result.attempted_task_ids == ("research-task", "research-task-2")
        assert result.failures == ()
        assert [snapshot.status for snapshot in snapshots] == [
            "cancelling",
            "cancelled",
        ]
        assert {call[1] for call in canceller.calls} == {
            "research-task",
            "research-task-2",
        }
        assert all(call[2] == 2 for call in canceller.calls)
        assert machine.snapshot.status == "cancelled"
        with pytest.raises(InvalidWorkflowTransition):
            machine.transition("analyzing", active_step="analysis")

    asyncio.run(scenario())


def test_remote_failure_does_not_prevent_local_cancellation() -> None:
    async def scenario() -> None:
        machine = _active_machine()
        canceller = RecordingCanceller(failing_task_ids={"research-task"})
        coordinator = CancellationCoordinator(
            state_machine=machine,
            remote_canceller=canceller,
        )
        await coordinator.register(_agent(), "research-task")

        result = await coordinator.cancel("user closed the run")

        assert result.snapshot.status == "cancelled"
        assert len(result.failures) == 1
        assert result.failures[0].remote_task_id == "research-task"
        assert "remote cancellation failed" in result.failures[0].detail

    asyncio.run(scenario())


def test_late_remote_task_is_cancelled_and_repeated_cancel_is_idempotent() -> None:
    async def scenario() -> None:
        machine = _active_machine()
        canceller = RecordingCanceller()
        coordinator = CancellationCoordinator(
            state_machine=machine,
            remote_canceller=canceller,
        )

        first = await coordinator.cancel("user cancelled")
        late_failure = await coordinator.register(_agent(), "late-task")
        second = await coordinator.cancel("duplicate cancellation event")

        assert late_failure is None
        assert [call[1] for call in canceller.calls] == ["late-task"]
        assert first is second
        assert machine.snapshot.status == "cancelled"

    asyncio.run(scenario())


def test_concurrent_cancellation_requests_share_one_propagation() -> None:
    async def scenario() -> None:
        machine = _active_machine()
        canceller = BlockingCanceller()
        coordinator = CancellationCoordinator(
            state_machine=machine,
            remote_canceller=canceller,
        )
        await coordinator.register(_agent(), "research-task")

        first_request = asyncio.create_task(coordinator.cancel("first request"))
        await canceller.started.wait()
        second_request = asyncio.create_task(coordinator.cancel("second request"))
        await asyncio.sleep(0)
        canceller.release.set()
        first, second = await asyncio.gather(first_request, second_request)

        assert first is second
        assert [call[1] for call in canceller.calls] == ["research-task"]
        assert machine.snapshot.status == "cancelled"

    asyncio.run(scenario())


def test_cancellation_after_other_terminal_outcome_is_rejected() -> None:
    async def scenario() -> None:
        machine = _active_machine()
        machine.transition("analyzing", active_step="analysis")
        machine.transition("completed")
        coordinator = CancellationCoordinator(
            state_machine=machine,
            remote_canceller=RecordingCanceller(),
        )

        with pytest.raises(CancellationRejectedError, match="completed"):
            await coordinator.cancel("too late")

    asyncio.run(scenario())
