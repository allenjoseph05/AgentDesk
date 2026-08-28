"""Coordinator command layer for adaptive decision intake."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from agents.coordinator.a2a_client import A2AClientAdapter, RemoteTaskResult
from agents.coordinator.a2ui import compile_intake_surface
from agents.coordinator.intake import direct_research_request, request_is_complete
from agents.coordinator.persistence import WorkflowPersistenceService
from agents.coordinator.projection import DurableAgUiProjector
from agents.coordinator.registry import AgentRegistry, RegisteredAgent
from agents.coordinator.run_adapter import (
    CoordinatorA2uiSurfaceUpdate,
    CoordinatorCommand,
    CoordinatorCommandExecutor,
    CoordinatorRunOutcome,
    CoordinatorRunUpdate,
    CoordinatorStateUpdate,
    PrepareResearchCommand,
    RemoteTaskCorrelation,
    SkipIntakeCommand,
    StartResearchCommand,
    SubmitIntakeCommand,
)
from agents.coordinator.workflow_state import TERMINAL_STATUSES, WorkflowStateMachine
from packages.contracts import (
    SCOPE_PROPOSAL_ARTIFACT_NAME,
    ScopeProposal,
    ScopeProposalArtifact,
    ScopingRequest,
)
from packages.persistence import AgentTaskRecord


class IntakeRemoteClient(Protocol):
    async def execute(
        self,
        *,
        agent: RegisteredAgent,
        request: ScopingRequest,
        artifact_name: str,
        payload_model: type[ScopeProposal],
        timeout_seconds: float,
        on_task_started: Callable[[str], Awaitable[None]] | None = None,
    ) -> RemoteTaskResult[ScopeProposal]: ...

    async def cancel(
        self,
        *,
        agent: RegisteredAgent,
        remote_task_id: str,
        timeout_seconds: float,
    ) -> None: ...


class AdaptiveIntakeCommandExecutor:
    """Handle intake commands and delegate research commands unchanged."""

    def __init__(
        self,
        *,
        downstream: CoordinatorCommandExecutor,
        registry: AgentRegistry,
        persistence: WorkflowPersistenceService,
        projector: DurableAgUiProjector,
        remote_client: IntakeRemoteClient | None = None,
        timeout_seconds: float = 10,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Scoping timeout must be positive.")
        self._downstream = downstream
        self._registry = registry
        self._persistence = persistence
        self._projector = projector
        self._remote = remote_client or A2AClientAdapter()
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, command: CoordinatorCommand) -> AsyncIterator[CoordinatorRunUpdate]:
        if isinstance(command, PrepareResearchCommand):
            if request_is_complete(command.request):
                async for update in self._downstream.execute(
                    StartResearchCommand(
                        correlation=command.correlation,
                        request=direct_research_request(command.request),
                        user_message=command.user_message,
                        action_type="prepare_research",
                    )
                ):
                    yield update
                return
            async for update in self._prepare(command):
                yield update
            return
        if isinstance(command, SubmitIntakeCommand):
            async for update in self._resume(command, skipped=False):
                yield update
            return
        if isinstance(command, SkipIntakeCommand):
            async for update in self._resume(command, skipped=True):
                yield update
            return
        async for update in self._downstream.execute(command):
            yield update

    async def _prepare(
        self,
        command: PrepareResearchCommand,
    ) -> AsyncIterator[CoordinatorRunUpdate]:
        machine = WorkflowStateMachine(
            command.correlation.session_id,
            clock=self._clock,
            on_transition=self._persistence.persist_transition,
        )
        task_id = _scoping_task_id(
            command.correlation.session_id,
            command.correlation.run_id,
        )
        agent: RegisteredAgent | None = None
        remote_task_id: str | None = None
        initialized = False
        try:
            self._persistence.initialize(
                snapshot=machine.snapshot,
                ag_ui_thread_id=command.correlation.thread_id,
                run_id=command.correlation.run_id,
                action_id=command.correlation.action_id,
                action_type="prepare_research",
                question=command.request.question,
                owner_id=command.correlation.principal_id,
            )
            initialized = True
            self._persistence.start_run(command.correlation.run_id)
            self._persistence.ensure_remote_task_capacity(command.correlation.session_id, 1)
            machine.transition("scoping", active_step="decision-scoping")
            agent = self._registry.first_by_skill("decision-scoping")
            if agent is None:
                raise RuntimeError("Decision-scoping capability is unavailable.")
            self._persistence.create_agent_task(
                AgentTaskRecord(
                    id=task_id,
                    session_id=command.correlation.session_id,
                    run_id=command.correlation.run_id,
                    agent_id=agent.agent_id,
                    skill="decision-scoping",
                    started_at=machine.snapshot.updated_at,
                )
            )

            async def task_started(task_identity: str) -> None:
                nonlocal remote_task_id
                remote_task_id = task_identity
                self._persistence.register_remote_task(
                    task_id,
                    remote_task_id=task_identity,
                )

            result = await self._remote.execute(
                agent=agent,
                request=command.request,
                artifact_name=SCOPE_PROPOSAL_ARTIFACT_NAME,
                payload_model=ScopeProposal,
                timeout_seconds=self._timeout_seconds,
                on_task_started=task_started,
            )
            remote_task_id = result.remote_task_id
            self._persistence.register_remote_task(
                task_id,
                remote_task_id=result.remote_task_id,
                a2a_context_id=result.remote_context_id,
            )
            self._persistence.finish_agent_task(
                task_id,
                status="completed",
                finished_at=self._clock(),
            )
            artifact = ScopeProposalArtifact.model_validate(
                result.artifact.model_dump(mode="python")
            )
            surface = compile_intake_surface(
                command.correlation.session_id,
                artifact.payload,
            )
            self._persistence.persist_intake_proposal(
                session_id=command.correlation.session_id,
                agent_task_id=task_id,
                request=command.request,
                artifact=artifact,
            )
            machine.transition(
                "awaiting_input",
                active_step="await-intake-response",
                completed_steps=["decision-scoping"],
            )
            self._persistence.finish_run(
                command.correlation.run_id,
                status="completed",
                finished_at=machine.snapshot.updated_at,
            )
            yield CoordinatorStateUpdate(
                self._projector.snapshot(command.correlation.session_id),
                sequence=machine.history[-1].sequence,
            )
            yield CoordinatorA2uiSurfaceUpdate(surface)
            yield CoordinatorRunOutcome(
                status="completed",
                message="Clarification questions are ready.",
                remote_tasks=(
                    RemoteTaskCorrelation(
                        agent_id=result.agent_id,
                        remote_task_id=result.remote_task_id,
                        a2a_context_id=result.remote_context_id,
                    ),
                ),
            )
        except asyncio.CancelledError:
            if agent is not None and remote_task_id is not None:
                with suppress(Exception):
                    await self._remote.cancel(
                        agent=agent,
                        remote_task_id=remote_task_id,
                        timeout_seconds=self._timeout_seconds,
                    )
            if initialized:
                self._cancel_prepare(machine, command, task_id)
            raise
        except Exception:
            if initialized:
                self._fail_prepare(machine, command, task_id)
                yield CoordinatorStateUpdate(
                    self._projector.snapshot(command.correlation.session_id),
                    sequence=(machine.history[-1].sequence if machine.history else None),
                )
            yield CoordinatorRunOutcome(
                status="failed",
                message="Decision scoping failed; use the direct research form instead.",
                error_code="decision_scoping_failed",
            )

    async def _resume(
        self,
        command: SubmitIntakeCommand | SkipIntakeCommand,
        *,
        skipped: bool,
    ) -> AsyncIterator[CoordinatorRunUpdate]:
        started_at = self._clock()
        try:
            self._persistence.continue_session(
                session_id=command.correlation.session_id,
                ag_ui_thread_id=command.correlation.thread_id,
                run_id=command.correlation.run_id,
                action_id=command.correlation.action_id,
                action_type="skip_intake" if skipped else "submit_intake",
                started_at=started_at,
                owner_id=command.correlation.principal_id,
            )
            self._persistence.start_run(command.correlation.run_id)
            if isinstance(command, SkipIntakeCommand):
                request = self._persistence.skip_intake(
                    session_id=command.correlation.session_id,
                    decided_at=started_at,
                )
            else:
                request = self._persistence.accept_intake_response(
                    session_id=command.correlation.session_id,
                    action_id=command.correlation.action_id,
                    response=command.response,
                    decided_at=started_at,
                )
        except Exception:
            with suppress(Exception):
                self._persistence.finish_run(
                    command.correlation.run_id,
                    status="failed",
                    finished_at=self._clock(),
                )
            yield CoordinatorRunOutcome(
                status="failed",
                message="The intake response was stale or invalid.",
                error_code="invalid_intake_response",
            )
            return

        async for update in self._downstream.execute(
            StartResearchCommand(
                correlation=command.correlation,
                request=request,
                user_message=command.user_message,
                resume_session=True,
                run_initialized=True,
                action_type="skip_intake" if skipped else "submit_intake",
            )
        ):
            yield update

    def _cancel_prepare(
        self,
        machine: WorkflowStateMachine,
        command: PrepareResearchCommand,
        task_id: str,
    ) -> None:
        finished = self._clock()
        with suppress(Exception):
            self._persistence.finish_agent_task(
                task_id,
                status="cancelled",
                finished_at=finished,
            )
        if machine.snapshot.status not in TERMINAL_STATUSES:
            machine.transition("cancelling", active_step="cancel-active-tasks")
            machine.transition("cancelled", reason="Browser cancelled adaptive intake.")
        self._persistence.finish_run(
            command.correlation.run_id,
            status="cancelled",
            finished_at=machine.snapshot.updated_at,
        )

    def _fail_prepare(
        self,
        machine: WorkflowStateMachine,
        command: PrepareResearchCommand,
        task_id: str,
    ) -> None:
        finished = self._clock()
        with suppress(Exception):
            self._persistence.finish_agent_task(
                task_id,
                status="failed",
                finished_at=finished,
                error_code="decision_scoping_failed",
                error_message="Decision scoping failed.",
            )
        if machine.snapshot.status not in TERMINAL_STATUSES:
            machine.transition(
                "failed",
                failed_steps=["decision-scoping"],
                reason="Decision scoping failed.",
            )
        self._persistence.finish_run(
            command.correlation.run_id,
            status="failed",
            finished_at=machine.snapshot.updated_at,
        )


def _scoping_task_id(session_id: str, run_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"agentdesk:{session_id}:run:{run_id}:decision-scoping"))
