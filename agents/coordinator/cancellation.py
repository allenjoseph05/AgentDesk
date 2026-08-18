"""Race-safe cancellation propagation for Coordinator workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from agents.coordinator.registry import RegisteredAgent
from agents.coordinator.workflow_state import (
    TERMINAL_STATUSES,
    WorkflowSnapshot,
    WorkflowStateMachine,
)


class RemoteTaskCanceller(Protocol):
    async def cancel(
        self,
        *,
        agent: RegisteredAgent,
        remote_task_id: str,
        timeout_seconds: float,
    ) -> None: ...


StateSnapshotHandler = Callable[[WorkflowSnapshot], Awaitable[None]]


@dataclass(frozen=True)
class RemoteCancellationFailure:
    """One best-effort remote cancellation that did not succeed."""

    agent_id: str
    remote_task_id: str
    detail: str


@dataclass(frozen=True)
class CancellationResult:
    """Terminal local outcome and diagnostics for remote cancellation attempts."""

    snapshot: WorkflowSnapshot
    attempted_task_ids: tuple[str, ...]
    failures: tuple[RemoteCancellationFailure, ...]
    notification_errors: tuple[str, ...] = ()


class CancellationRejectedError(RuntimeError):
    """Raised when cancellation arrives after a different terminal outcome."""


class CancellationCoordinator:
    """Cancel local workflow state and every registered remote A2A task."""

    def __init__(
        self,
        *,
        state_machine: WorkflowStateMachine,
        remote_canceller: RemoteTaskCanceller,
        timeout_seconds: float = 10,
        on_state_snapshot: StateSnapshotHandler | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Remote cancellation timeout must be positive.")
        self._state_machine = state_machine
        self._remote_canceller = remote_canceller
        self._timeout_seconds = timeout_seconds
        self._on_state_snapshot = on_state_snapshot
        self._active_tasks: dict[str, RegisteredAgent] = {}
        self._attempted_task_ids: set[str] = set()
        self._lock = asyncio.Lock()
        self._cancellation_task: asyncio.Task[CancellationResult] | None = None
        self._result: CancellationResult | None = None

    async def register(
        self, agent: RegisteredAgent, remote_task_id: str
    ) -> RemoteCancellationFailure | None:
        """Track active work, or immediately cancel work registered after cancellation."""
        if not remote_task_id.strip():
            raise ValueError("Remote task ID cannot be blank.")
        cancel_immediately = False
        async with self._lock:
            existing = self._active_tasks.get(remote_task_id)
            if existing is not None and existing.agent_id != agent.agent_id:
                raise ValueError("Remote task ID is already registered to another agent.")

            status = self._state_machine.snapshot.status
            if status in {"cancelling", "cancelled"}:
                if remote_task_id not in self._attempted_task_ids:
                    self._attempted_task_ids.add(remote_task_id)
                    cancel_immediately = True
            elif status in TERMINAL_STATUSES:
                raise CancellationRejectedError(
                    f"Cannot register remote work after workflow reached {status}."
                )
            else:
                self._active_tasks[remote_task_id] = agent

        if cancel_immediately:
            return await self._cancel_one(agent, remote_task_id)
        return None

    async def complete(self, remote_task_id: str) -> None:
        """Forget completed remote work without changing workflow state."""
        async with self._lock:
            self._active_tasks.pop(remote_task_id, None)

    async def cancel(self, reason: str) -> CancellationResult:
        """Idempotently make local cancellation terminal and propagate it remotely."""
        if not reason.strip():
            raise ValueError("Cancellation reason cannot be blank.")
        async with self._lock:
            if self._result is not None:
                return self._result
            status = self._state_machine.snapshot.status
            if status in TERMINAL_STATUSES and status != "cancelled":
                raise CancellationRejectedError(
                    f"Workflow already reached terminal status {status}."
                )
            if status == "cancelled":
                self._result = CancellationResult(
                    snapshot=self._state_machine.snapshot,
                    attempted_task_ids=tuple(sorted(self._attempted_task_ids)),
                    failures=(),
                )
                return self._result
            if self._cancellation_task is None:
                self._cancellation_task = asyncio.create_task(self._run_cancel(reason))
            cancellation_task = self._cancellation_task
        return await asyncio.shield(cancellation_task)

    async def _run_cancel(self, reason: str) -> CancellationResult:
        notification_errors: list[str] = []
        async with self._lock:
            if self._state_machine.snapshot.status != "cancelling":
                cancelling = self._state_machine.transition(
                    "cancelling",
                    active_step="cancellation",
                    reason=reason,
                )
            else:
                cancelling = self._state_machine.snapshot
            active_tasks = tuple(self._active_tasks.items())
            self._attempted_task_ids.update(task_id for task_id, _ in active_tasks)

        await self._notify(cancelling, notification_errors)
        outcomes = await asyncio.gather(
            *(
                self._cancel_one(agent, remote_task_id)
                for remote_task_id, agent in active_tasks
            )
        )
        failures = tuple(outcome for outcome in outcomes if outcome is not None)

        async with self._lock:
            for remote_task_id, _ in active_tasks:
                self._active_tasks.pop(remote_task_id, None)
            cancelled = self._state_machine.transition("cancelled", reason=reason)

        await self._notify(cancelled, notification_errors)
        result = CancellationResult(
            snapshot=cancelled,
            attempted_task_ids=tuple(sorted(task_id for task_id, _ in active_tasks)),
            failures=failures,
            notification_errors=tuple(notification_errors),
        )
        async with self._lock:
            self._result = result
        return result

    async def _cancel_one(
        self, agent: RegisteredAgent, remote_task_id: str
    ) -> RemoteCancellationFailure | None:
        try:
            await self._remote_canceller.cancel(
                agent=agent,
                remote_task_id=remote_task_id,
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as error:
            return RemoteCancellationFailure(
                agent_id=agent.agent_id,
                remote_task_id=remote_task_id,
                detail=str(error) or type(error).__name__,
            )
        return None

    async def _notify(
        self, snapshot: WorkflowSnapshot, errors: list[str]
    ) -> None:
        if self._on_state_snapshot is None:
            return
        try:
            await self._on_state_snapshot(snapshot.model_copy(deep=True))
        except Exception as error:
            errors.append(str(error) or type(error).__name__)
