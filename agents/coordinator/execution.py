"""Durable command execution across planning and specialist orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Protocol

from agents.coordinator.a2a_client import RemoteTaskResult
from agents.coordinator.orchestrator import WorkflowExecution, WorkflowOrchestrator
from agents.coordinator.persistence import WorkflowPersistenceError, WorkflowPersistenceService
from agents.coordinator.planner import DecisionPlanner, PlanningFailedError, WorkflowPlan
from agents.coordinator.registry import AgentRegistry
from agents.coordinator.run_adapter import (
    ChallengeRecommendationCommand,
    CoordinatorCommand,
    CoordinatorRunOutcome,
    CoordinatorRunUpdate,
    FocusOnCriterionCommand,
    RemoteTaskCorrelation,
    ResearchDeeperCommand,
    RetryFailedAgentCommand,
    StartResearchCommand,
)
from agents.coordinator.workflow_state import TERMINAL_STATUSES, WorkflowStateMachine
from packages.contracts import DecisionAnalysis, EvidenceBundle, ResearchRequest
from packages.llm import llm_provider_from_environment
from packages.persistence import Database, RepositoryError


class WorkflowPlanner(Protocol):
    async def plan(self, request: ResearchRequest) -> WorkflowPlan: ...


class WorkflowRunner(Protocol):
    async def execute(self, request: ResearchRequest, plan: WorkflowPlan) -> WorkflowExecution: ...


class OrchestrationConfigurationError(RuntimeError):
    """The production planning provider has not been configured."""

    code = "coordinator_not_configured"


class _UnavailablePlanner:
    async def plan(self, request: ResearchRequest) -> WorkflowPlan:
        del request
        raise OrchestrationConfigurationError(
            "Coordinator planning requires OPENAI_API_KEY and "
            "AGENTDESK_COORDINATOR_MODEL."
        )


class OrchestrationCommandExecutor:
    """Execute typed Coordinator commands against durable workflow services."""

    def __init__(
        self,
        *,
        planner: WorkflowPlanner,
        orchestrator: WorkflowRunner,
        persistence: WorkflowPersistenceService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._planner = planner
        self._orchestrator = orchestrator
        self._persistence = persistence
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self, command: CoordinatorCommand
    ) -> AsyncIterator[CoordinatorRunUpdate]:
        if not isinstance(command, StartResearchCommand):
            yield self._record_unsupported_follow_up(command)
            return

        machine = WorkflowStateMachine(
            command.correlation.session_id,
            clock=self._clock,
            on_transition=self._persistence.persist_transition,
        )
        initialized = False
        try:
            self._persistence.initialize(
                snapshot=machine.snapshot,
                ag_ui_thread_id=command.correlation.thread_id,
                run_id=command.correlation.run_id,
                action_id=command.correlation.action_id,
                action_type="start_research",
                question=command.request.question,
            )
            initialized = True
            self._persistence.start_run(command.correlation.run_id)
            machine.transition("planning", active_step="plan")
            plan = await self._planner.plan(command.request)
            machine.transition(
                "researching",
                active_step="research",
                completed_steps=["plan"],
            )
            execution = await self._orchestrator.execute(command.request, plan)
            machine.transition(
                "analyzing",
                active_step="analysis",
                completed_steps=["research"],
            )
            machine.transition("completed", completed_steps=["analysis"])
            self._persistence.finish_run(
                command.correlation.run_id,
                status="completed",
                finished_at=machine.snapshot.updated_at,
            )
        except asyncio.CancelledError:
            if initialized:
                self._cancel_run(command, machine)
            raise
        except Exception as error:
            if initialized:
                self._fail_run(command, machine)
            yield CoordinatorRunOutcome(
                status="failed",
                message=_safe_failure_message(error),
                error_code=_failure_code(error),
            )
            return

        yield CoordinatorRunOutcome(
            status="completed",
            message="Research and analysis completed.",
            remote_tasks=(
                _remote_correlation(execution.research),
                _remote_correlation(execution.analysis),
            ),
        )

    def _record_unsupported_follow_up(
        self,
        command: CoordinatorCommand,
    ) -> CoordinatorRunOutcome:
        action_type = _action_type(command)
        started_at = self._clock()
        try:
            self._persistence.continue_session(
                session_id=command.correlation.session_id,
                ag_ui_thread_id=command.correlation.thread_id,
                run_id=command.correlation.run_id,
                action_id=command.correlation.action_id,
                action_type=action_type,
                started_at=started_at,
            )
            self._persistence.start_run(command.correlation.run_id)
            self._persistence.finish_run(
                command.correlation.run_id,
                status="failed",
                finished_at=self._clock(),
            )
        except (RepositoryError, WorkflowPersistenceError):
            return CoordinatorRunOutcome(
                status="failed",
                message="The requested Coordinator session could not be continued.",
                error_code="invalid_session_correlation",
            )
        return CoordinatorRunOutcome(
            status="failed",
            message="Follow-up orchestration is introduced in AD-074.",
            error_code="follow_up_not_implemented",
        )

    def _cancel_run(
        self,
        command: StartResearchCommand,
        machine: WorkflowStateMachine,
    ) -> None:
        if machine.snapshot.status not in TERMINAL_STATUSES:
            machine.transition(
                "cancelling",
                active_step="cancel",
                reason="The browser cancelled the Coordinator run.",
            )
            machine.transition(
                "cancelled",
                reason="The browser cancelled the Coordinator run.",
            )
        self._persistence.finish_run(
            command.correlation.run_id,
            status="cancelled",
            finished_at=machine.snapshot.updated_at,
        )

    def _fail_run(
        self,
        command: StartResearchCommand,
        machine: WorkflowStateMachine,
    ) -> None:
        if machine.snapshot.status not in TERMINAL_STATUSES:
            active_step = machine.snapshot.active_step
            machine.transition(
                "failed",
                failed_steps=([active_step] if active_step is not None else []),
                reason="Coordinator orchestration failed.",
            )
        try:
            self._persistence.finish_run(
                command.correlation.run_id,
                status="failed",
                finished_at=machine.snapshot.updated_at,
            )
        except WorkflowPersistenceError:
            # Initialization itself can fail before a durable run exists.
            return


def create_orchestration_executor(
    *,
    registry: AgentRegistry,
    database: Database,
) -> OrchestrationCommandExecutor:
    """Build the production executor without contacting external services eagerly."""
    llm_provider = llm_provider_from_environment()
    planner: WorkflowPlanner
    if llm_provider is not None:
        planner = DecisionPlanner(
            llm_provider=llm_provider,
            registry=registry,
        )
    else:
        planner = _UnavailablePlanner()
    return OrchestrationCommandExecutor(
        planner=planner,
        orchestrator=WorkflowOrchestrator(registry=registry),
        persistence=WorkflowPersistenceService(database),
    )


def _remote_correlation(
    result: RemoteTaskResult[EvidenceBundle] | RemoteTaskResult[DecisionAnalysis],
) -> RemoteTaskCorrelation:
    return RemoteTaskCorrelation(
        agent_id=result.agent_id,
        remote_task_id=result.remote_task_id,
        a2a_context_id=result.remote_context_id,
    )


def _failure_code(error: Exception) -> str:
    if isinstance(error, PlanningFailedError):
        return f"planning_{error.code}"
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code.strip() else "orchestration_failed"


def _safe_failure_message(error: Exception) -> str:
    if isinstance(error, OrchestrationConfigurationError):
        return str(error)
    if isinstance(error, PlanningFailedError):
        return "The Coordinator could not produce a valid research plan."
    return "The Coordinator could not complete research orchestration."


def _action_type(command: CoordinatorCommand) -> str:
    if isinstance(command, ChallengeRecommendationCommand):
        return "challenge_recommendation"
    if isinstance(command, ResearchDeeperCommand):
        return "research_deeper"
    if isinstance(command, FocusOnCriterionCommand):
        return "focus_on_criterion"
    if isinstance(command, RetryFailedAgentCommand):
        return "retry_failed_agent"
    return "start_research"
