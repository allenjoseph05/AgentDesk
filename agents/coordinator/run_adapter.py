"""Production AG-UI run admission and Coordinator command adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

from ag_ui.core import (
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder
from pydantic import ValidationError

from agents.coordinator.run_tasks import A2ATaskFactory, ActiveA2ATask
from packages.contracts import AgentDeskAction, AgentDeskViewState, ResearchRequest, SpecialistView
from packages.contracts.agui import (
    ChallengeRecommendationAction,
    FocusOnCriterionAction,
    ResearchDeeperAction,
    RetryFailedAgentAction,
    StartResearchAction,
)

TerminalRunStatus = Literal["completed", "partial", "cancelled", "failed"]


@dataclass(frozen=True)
class RunCorrelation:
    """Stable identifiers joining browser, Coordinator, and remote A2A work."""

    thread_id: str
    run_id: str
    action_id: str
    session_id: str


@dataclass(frozen=True)
class RemoteTaskCorrelation:
    """A specialist task identity associated with one Coordinator run."""

    agent_id: str
    remote_task_id: str
    a2a_context_id: str | None = None

    def __post_init__(self) -> None:
        if not self.agent_id.strip() or not self.remote_task_id.strip():
            raise ValueError("Remote task correlation identifiers cannot be blank.")
        if self.a2a_context_id is not None and not self.a2a_context_id.strip():
            raise ValueError("A2A context ID cannot be blank when supplied.")

    def to_ag_ui(self) -> dict[str, str | None]:
        return {
            "agentId": self.agent_id,
            "remoteTaskId": self.remote_task_id,
            "a2aContextId": self.a2a_context_id,
        }


@dataclass(frozen=True)
class StartResearchCommand:
    correlation: RunCorrelation
    request: ResearchRequest
    user_message: str


@dataclass(frozen=True)
class ChallengeRecommendationCommand:
    correlation: RunCorrelation
    challenge: str | None
    user_message: str


@dataclass(frozen=True)
class ResearchDeeperCommand:
    correlation: RunCorrelation
    focus_areas: tuple[str, ...]
    desired_depth: Literal["normal", "deep"]
    user_message: str


@dataclass(frozen=True)
class FocusOnCriterionCommand:
    correlation: RunCorrelation
    criterion: str
    user_message: str


@dataclass(frozen=True)
class RetryFailedAgentCommand:
    correlation: RunCorrelation
    agent_id: str
    remote_task_id: str | None
    user_message: str


CoordinatorCommand = (
    StartResearchCommand
    | ChallengeRecommendationCommand
    | ResearchDeeperCommand
    | FocusOnCriterionCommand
    | RetryFailedAgentCommand
)


@dataclass(frozen=True)
class CoordinatorStateUpdate:
    """A complete state committed by an executor during one run."""

    snapshot: AgentDeskViewState


@dataclass(frozen=True)
class CoordinatorRunOutcome:
    """One terminal Coordinator result mapped to an AG-UI terminal event."""

    status: TerminalRunStatus
    message: str | None = None
    error_code: str | None = None
    remote_tasks: tuple[RemoteTaskCorrelation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status == "failed" and not self.error_code:
            raise ValueError("Failed Coordinator outcomes require an error code.")
        if self.status != "failed" and self.error_code is not None:
            raise ValueError("Only failed Coordinator outcomes may carry an error code.")
        task_keys = [
            (task.agent_id, task.remote_task_id) for task in self.remote_tasks
        ]
        if len(task_keys) != len(set(task_keys)):
            raise ValueError("Remote task correlations must be unique.")


CoordinatorRunUpdate = CoordinatorStateUpdate | CoordinatorRunOutcome


class CoordinatorCommandExecutor(Protocol):
    """UI-neutral execution boundary implemented by Coordinator application services."""

    def execute(self, command: CoordinatorCommand) -> AsyncIterator[CoordinatorRunUpdate]: ...


class AcceptingCommandExecutor:
    """Default shell executor used until orchestration is wired in AD-071."""

    async def execute(self, command: CoordinatorCommand) -> AsyncIterator[CoordinatorRunUpdate]:
        yield CoordinatorRunOutcome(
            status="completed",
            message="Coordinator command accepted. Workflow execution will begin next.",
        )


@dataclass(frozen=True)
class _Admission:
    fingerprint: str
    correlation: RunCorrelation


class DuplicateActionError(RuntimeError):
    """Raised when an idempotency key has already admitted a run."""

    def __init__(self, *, conflicting: bool) -> None:
        self.conflicting = conflicting
        message = (
            "Action ID was reused with different run data."
            if conflicting
            else "Action ID has already been accepted."
        )
        super().__init__(message)


class RunAdmissionRegistry:
    """Atomically admit each action ID at most once within a Coordinator process."""

    def __init__(self) -> None:
        self._admissions: dict[str, _Admission] = {}
        self._lock = asyncio.Lock()

    async def admit(
        self,
        *,
        input_data: RunAgentInput,
        action: AgentDeskAction,
    ) -> RunCorrelation:
        fingerprint = _action_fingerprint(input_data.thread_id, action)
        async with self._lock:
            existing = self._admissions.get(action.root.action_id)
            if existing is not None:
                raise DuplicateActionError(
                    conflicting=existing.fingerprint != fingerprint
                )
            correlation = _correlation(input_data, action)
            self._admissions[action.root.action_id] = _Admission(
                fingerprint=fingerprint,
                correlation=correlation,
            )
            return correlation


class CoordinatorRunAdapter:
    """Translate one official AG-UI run into a typed Coordinator command stream."""

    def __init__(
        self,
        *,
        executor: CoordinatorCommandExecutor | None = None,
        admissions: RunAdmissionRegistry | None = None,
    ) -> None:
        self._executor = executor or AcceptingCommandExecutor()
        self._admissions = admissions or RunAdmissionRegistry()

    async def stream(
        self,
        input_data: RunAgentInput,
        encoder: EventEncoder,
    ) -> AsyncIterator[str]:
        yield encoder.encode(
            RunStartedEvent(threadId=input_data.thread_id, runId=input_data.run_id)
        )

        try:
            action = _agentdesk_action(input_data)
            user_message = _latest_user_text(input_data)
            _validate_action_message(action, user_message)
        except (ValidationError, ValueError) as error:
            code = (
                "action_message_mismatch"
                if isinstance(error, ActionMessageMismatchError)
                else "invalid_agentdesk_action"
            )
            message = (
                str(error)
                if isinstance(error, ActionMessageMismatchError)
                else "A valid AgentDesk action envelope is required."
            )
            yield encoder.encode(RunErrorEvent(message=message, code=code))
            return

        try:
            correlation = _correlation(input_data, action)
            command = _to_command(action, correlation, user_message)
            initial_state = _initial_state(input_data, command)
        except (ValidationError, ValueError):
            yield encoder.encode(
                RunErrorEvent(
                    message="The action does not match the supplied session state.",
                    code="invalid_session_state",
                )
            )
            return

        try:
            correlation = await self._admissions.admit(
                input_data=input_data,
                action=action,
            )
        except DuplicateActionError as error:
            yield encoder.encode(
                RunErrorEvent(
                    message=str(error),
                    code=(
                        "duplicate_action_conflict"
                        if error.conflicting
                        else "duplicate_action"
                    ),
                )
            )
            return

        step_name = _step_name(command)
        yield encoder.encode(StepStartedEvent(stepName=step_name))
        yield encoder.encode(StateSnapshotEvent(snapshot=initial_state.to_ag_ui()))

        terminal_seen = False
        try:
            async for update in self._executor.execute(command):
                if terminal_seen:
                    raise RuntimeError("Executor emitted data after its terminal outcome.")
                if isinstance(update, CoordinatorStateUpdate):
                    _validate_update_correlation(update.snapshot, correlation)
                    yield encoder.encode(
                        StateSnapshotEvent(snapshot=update.snapshot.to_ag_ui())
                    )
                    continue

                terminal_seen = True
                if update.status == "failed":
                    yield encoder.encode(
                        RunErrorEvent(
                            message=update.message or "The Coordinator run failed.",
                            code=update.error_code or "coordinator_run_failed",
                        )
                    )
                    return

                if update.message:
                    message_id = str(uuid4())
                    yield encoder.encode(
                        TextMessageStartEvent(messageId=message_id, role="assistant")
                    )
                    yield encoder.encode(
                        TextMessageContentEvent(
                            messageId=message_id,
                            delta=update.message,
                        )
                    )
                    yield encoder.encode(TextMessageEndEvent(messageId=message_id))
                yield encoder.encode(StepFinishedEvent(stepName=step_name))
                yield encoder.encode(
                    RunFinishedEvent(
                        threadId=correlation.thread_id,
                        runId=correlation.run_id,
                        result=_finished_result(correlation, update),
                    )
                )
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            yield encoder.encode(
                RunErrorEvent(
                    message="The Coordinator could not complete this run.",
                    code="coordinator_run_failed",
                )
            )
            return

        if not terminal_seen:
            yield encoder.encode(
                RunErrorEvent(
                    message="The Coordinator ended without a terminal outcome.",
                    code="missing_terminal_outcome",
                )
            )


class A2ATaskCommandExecutor:
    """Compatibility executor for the existing live A2A cancellation spike."""

    def __init__(self, task_factory: A2ATaskFactory) -> None:
        self._task_factory = task_factory

    async def execute(self, command: CoordinatorCommand) -> AsyncIterator[CoordinatorRunUpdate]:
        if not isinstance(command, StartResearchCommand):
            yield CoordinatorRunOutcome(
                status="failed",
                message="The A2A spike accepts start_research only.",
                error_code="unsupported_spike_action",
            )
            return

        active_task: ActiveA2ATask | None = None
        active_task_finished = False
        try:
            active_task = await self._task_factory.start(command.request.question)
            yield CoordinatorStateUpdate(
                AgentDeskViewState(
                    session_id=command.correlation.session_id,
                    question=command.request.question,
                    status="researching",
                    active_step="research",
                    agents=[
                        SpecialistView(
                            agent_id="cancellation-spike-agent",
                            name="A2A cancellation spike",
                            skill="research",
                            status="working",
                            remote_task_id=active_task.remote_task_id,
                        )
                    ],
                    last_updated_at=datetime.now(UTC),
                )
            )
            await active_task.wait()
            active_task_finished = True
            yield CoordinatorRunOutcome(
                status="completed",
                message="Research request accepted. Planning will begin next.",
                remote_tasks=(
                    RemoteTaskCorrelation(
                        agent_id="cancellation-spike-agent",
                        remote_task_id=active_task.remote_task_id,
                    ),
                ),
            )
        except asyncio.CancelledError:
            if active_task is not None and not active_task_finished:
                await active_task.cancel()
            raise
        finally:
            if active_task is not None:
                with suppress(Exception):
                    await active_task.aclose()


class ActionMessageMismatchError(ValueError):
    """Raised when human-readable transcript and machine action disagree."""


def _agentdesk_action(input_data: RunAgentInput) -> AgentDeskAction:
    forwarded_props = input_data.forwarded_props
    if not isinstance(forwarded_props, dict) or "agentdesk" not in forwarded_props:
        raise ValueError("forwardedProps.agentdesk is required.")
    return AgentDeskAction.model_validate(forwarded_props["agentdesk"])


def _latest_user_text(input_data: RunAgentInput) -> str:
    for message in reversed(input_data.messages):
        if message.role == "user" and isinstance(message.content, str):
            text = message.content.strip()
            if text:
                return text
    raise ActionMessageMismatchError("A non-empty user message is required.")


def _validate_action_message(action: AgentDeskAction, user_message: str) -> None:
    root = action.root
    expected: str | None = None
    if isinstance(root, StartResearchAction):
        expected = root.payload.question
    elif isinstance(root, ChallengeRecommendationAction):
        expected = root.payload.challenge
    if expected is not None and user_message != expected:
        raise ActionMessageMismatchError(
            "The user message and structured action payload must match."
        )


def _to_command(
    action: AgentDeskAction,
    correlation: RunCorrelation,
    user_message: str,
) -> CoordinatorCommand:
    root = action.root
    if isinstance(root, StartResearchAction):
        return StartResearchCommand(
            correlation=correlation,
            request=ResearchRequest.model_validate(root.payload.model_dump()),
            user_message=user_message,
        )
    if isinstance(root, ChallengeRecommendationAction):
        return ChallengeRecommendationCommand(
            correlation=correlation,
            challenge=root.payload.challenge,
            user_message=user_message,
        )
    if isinstance(root, ResearchDeeperAction):
        return ResearchDeeperCommand(
            correlation=correlation,
            focus_areas=tuple(root.payload.focus_areas),
            desired_depth=root.payload.desired_depth,
            user_message=user_message,
        )
    if isinstance(root, FocusOnCriterionAction):
        return FocusOnCriterionCommand(
            correlation=correlation,
            criterion=root.payload.criterion,
            user_message=user_message,
        )
    if isinstance(root, RetryFailedAgentAction):
        return RetryFailedAgentCommand(
            correlation=correlation,
            agent_id=root.payload.agent_id,
            remote_task_id=root.payload.remote_task_id,
            user_message=user_message,
        )
    raise TypeError("Unsupported AgentDesk action type.")


def _initial_state(
    input_data: RunAgentInput,
    command: CoordinatorCommand,
) -> AgentDeskViewState:
    if isinstance(command, StartResearchCommand):
        return AgentDeskViewState(
            session_id=command.correlation.session_id,
            question=command.request.question,
            status="planning",
            active_step=_step_name(command),
            last_updated_at=datetime.now(UTC),
        )

    previous = AgentDeskViewState.model_validate(input_data.state)
    if previous.session_id != command.correlation.session_id:
        raise ValueError("Action session does not match AG-UI state.")
    return previous.model_copy(
        update={
            "status": "planning",
            "active_step": _step_name(command),
            "last_updated_at": datetime.now(UTC),
        },
        deep=True,
    )


def _step_name(command: CoordinatorCommand) -> str:
    if isinstance(command, StartResearchCommand):
        return "accept-research-request"
    if isinstance(command, ChallengeRecommendationCommand):
        return "challenge-recommendation"
    if isinstance(command, ResearchDeeperCommand):
        return "research-deeper"
    if isinstance(command, FocusOnCriterionCommand):
        return "focus-on-criterion"
    return "retry-failed-agent"


def _validate_update_correlation(
    snapshot: AgentDeskViewState,
    correlation: RunCorrelation,
) -> None:
    if snapshot.session_id != correlation.session_id:
        raise ValueError("Executor state belongs to another Coordinator session.")


def _finished_result(
    correlation: RunCorrelation,
    outcome: CoordinatorRunOutcome,
) -> dict[str, object]:
    return {
        "threadId": correlation.thread_id,
        "runId": correlation.run_id,
        "sessionId": correlation.session_id,
        "actionId": correlation.action_id,
        "status": outcome.status,
        "remoteTasks": [task.to_ag_ui() for task in outcome.remote_tasks],
    }


def _action_fingerprint(thread_id: str, action: AgentDeskAction) -> str:
    return json.dumps(
        {"threadId": thread_id, "action": action.to_ag_ui()},
        sort_keys=True,
        separators=(",", ":"),
    )


def _correlation(
    input_data: RunAgentInput,
    action: AgentDeskAction,
) -> RunCorrelation:
    return RunCorrelation(
        thread_id=input_data.thread_id,
        run_id=input_data.run_id,
        action_id=action.root.action_id,
        session_id=action.root.session_id or input_data.run_id,
    )
