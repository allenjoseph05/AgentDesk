"""Explicit, UI-neutral Coordinator workflow state machine."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from packages.contracts.base import ContractModel, NonEmptyText

WorkflowStatus = Literal[
    "created",
    "planning",
    "researching",
    "analyzing",
    "verifying",
    "cancelling",
    "completed",
    "partial",
    "failed",
    "cancelled",
]
TransitionObserver = Callable[["WorkflowSnapshot", "WorkflowTransition"], object]

TERMINAL_STATUSES: frozenset[WorkflowStatus] = frozenset(
    {"completed", "partial", "failed", "cancelled"}
)
ACTIVE_STATUSES: frozenset[WorkflowStatus] = frozenset(
    {"planning", "researching", "analyzing", "verifying", "cancelling"}
)
LEGAL_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    "created": frozenset({"planning", "cancelling", "failed"}),
    "planning": frozenset({"researching", "cancelling", "failed"}),
    "researching": frozenset({"analyzing", "partial", "cancelling", "failed"}),
    "analyzing": frozenset(
        {"verifying", "completed", "partial", "cancelling", "failed"}
    ),
    "verifying": frozenset({"completed", "partial", "cancelling", "failed"}),
    "cancelling": frozenset({"cancelled", "failed"}),
    "completed": frozenset(),
    "partial": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


class WorkflowSnapshot(ContractModel):
    """Current durable workflow state, independent from its UI projection."""

    session_id: NonEmptyText
    status: WorkflowStatus = "created"
    active_step: NonEmptyText | None = None
    completed_steps: list[NonEmptyText] = Field(default_factory=list)
    failed_steps: list[NonEmptyText] = Field(default_factory=list)
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_consistency(self) -> WorkflowSnapshot:
        if self.status in ACTIVE_STATUSES and self.active_step is None:
            raise ValueError("Active workflow status requires an active step.")
        if self.status in TERMINAL_STATUSES and self.active_step is not None:
            raise ValueError("Terminal workflow status cannot retain an active step.")
        if len(self.completed_steps) != len(set(self.completed_steps)):
            raise ValueError("Completed workflow steps must be unique.")
        if len(self.failed_steps) != len(set(self.failed_steps)):
            raise ValueError("Failed workflow steps must be unique.")
        overlap = set(self.completed_steps) & set(self.failed_steps)
        if overlap:
            raise ValueError(f"Workflow steps cannot both succeed and fail: {sorted(overlap)}")
        if self.status == "partial" and not (self.completed_steps and self.failed_steps):
            raise ValueError("Partial workflow requires completed and failed steps.")
        return self


class WorkflowTransition(ContractModel):
    """One accepted state change retained for reconstruction and diagnostics."""

    sequence: int = Field(ge=1)
    from_status: WorkflowStatus
    to_status: WorkflowStatus
    active_step: NonEmptyText | None = None
    reason: NonEmptyText | None = None
    occurred_at: AwareDatetime


class InvalidWorkflowTransition(RuntimeError):
    """Raised when a transition violates the explicit workflow graph or invariants."""

    def __init__(
        self,
        from_status: WorkflowStatus,
        to_status: WorkflowStatus,
        message: str,
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(message)


class WorkflowStateMachine:
    """Apply atomic transitions while preventing terminal-state resurrection."""

    def __init__(
        self,
        session_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
        on_transition: TransitionObserver | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._on_transition = on_transition
        self._snapshot = WorkflowSnapshot(
            session_id=session_id,
            updated_at=self._clock(),
        )
        self._history: list[WorkflowTransition] = []

    @property
    def snapshot(self) -> WorkflowSnapshot:
        return self._snapshot.model_copy(deep=True)

    @property
    def history(self) -> tuple[WorkflowTransition, ...]:
        return tuple(item.model_copy(deep=True) for item in self._history)

    def transition(
        self,
        to_status: WorkflowStatus,
        *,
        active_step: str | None = None,
        completed_steps: Iterable[str] = (),
        failed_steps: Iterable[str] = (),
        reason: str | None = None,
    ) -> WorkflowSnapshot:
        """Validate and atomically apply one legal state transition."""
        from_status = self._snapshot.status
        if to_status not in LEGAL_TRANSITIONS[from_status]:
            raise InvalidWorkflowTransition(
                from_status,
                to_status,
                f"Workflow cannot transition from {from_status} to {to_status}.",
            )
        if to_status in ACTIVE_STATUSES and not (active_step and active_step.strip()):
            raise InvalidWorkflowTransition(
                from_status,
                to_status,
                f"Transition to {to_status} requires an active step.",
            )
        if to_status in TERMINAL_STATUSES and active_step is not None:
            raise InvalidWorkflowTransition(
                from_status,
                to_status,
                "Terminal transitions cannot retain an active step.",
            )
        if to_status in {"partial", "failed", "cancelled"} and not (reason and reason.strip()):
            raise InvalidWorkflowTransition(
                from_status,
                to_status,
                f"Transition to {to_status} requires a reason.",
            )

        timestamp = self._clock()
        try:
            completed = _merge_steps(self._snapshot.completed_steps, completed_steps)
            failed = _merge_steps(self._snapshot.failed_steps, failed_steps)
            candidate = WorkflowSnapshot(
                session_id=self._snapshot.session_id,
                status=to_status,
                active_step=active_step.strip() if active_step is not None else None,
                completed_steps=completed,
                failed_steps=failed,
                updated_at=timestamp,
            )
        except ValueError as error:
            raise InvalidWorkflowTransition(from_status, to_status, str(error)) from error

        transition = WorkflowTransition(
            sequence=len(self._history) + 1,
            from_status=from_status,
            to_status=to_status,
            active_step=candidate.active_step,
            reason=reason,
            occurred_at=timestamp,
        )
        if self._on_transition is not None:
            self._on_transition(
                candidate.model_copy(deep=True),
                transition.model_copy(deep=True),
            )
        self._snapshot = candidate
        self._history.append(transition)
        return candidate.model_copy(deep=True)


def _merge_steps(existing: list[str], additions: Iterable[str]) -> list[str]:
    merged = list(existing)
    for step in additions:
        normalized = step.strip()
        if not normalized:
            raise ValueError("Workflow step identifiers cannot be blank.")
        if normalized not in merged:
            merged.append(normalized)
    return merged
