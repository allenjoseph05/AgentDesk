"""Durable command execution across planning and specialist orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from agents.coordinator.a2a_client import RemoteTaskResult
from agents.coordinator.cancellation import CancellationCoordinator
from agents.coordinator.orchestrator import WorkflowExecution, WorkflowOrchestrator
from agents.coordinator.persistence import WorkflowPersistenceError, WorkflowPersistenceService
from agents.coordinator.planner import DecisionPlanner, PlanningFailedError, WorkflowPlan
from agents.coordinator.projection import DurableAgUiProjector
from agents.coordinator.registry import AgentRegistry, RegisteredAgent
from agents.coordinator.run_adapter import (
    ChallengeRecommendationCommand,
    CoordinatorActivityUpdate,
    CoordinatorCommand,
    CoordinatorRunOutcome,
    CoordinatorRunUpdate,
    CoordinatorStateUpdate,
    CoordinatorStepUpdate,
    FocusOnCriterionCommand,
    RemoteTaskCorrelation,
    ResearchDeeperCommand,
    RetryFailedAgentCommand,
    StartResearchCommand,
)
from agents.coordinator.workflow_state import TERMINAL_STATUSES, WorkflowStateMachine
from packages.contracts import (
    AnalysisRequest,
    DecisionAnalysis,
    EvidenceBundle,
    RecommendationChallenge,
    ResearchRequest,
    VerificationReport,
)
from packages.llm import llm_provider_from_environment
from packages.observability import CorrelationIds, observed_request
from packages.persistence import AgentTaskRecord, Database, RepositoryError

LOGGER = logging.getLogger(__name__)


class WorkflowPlanner(Protocol):
    async def plan(self, request: ResearchRequest) -> WorkflowPlan: ...


class WorkflowRunner(Protocol):
    async def execute(
        self,
        request: ResearchRequest,
        plan: WorkflowPlan,
        *,
        on_remote_task_started: (
            Callable[[RegisteredAgent, str], Awaitable[None]] | None
        ) = None,
        on_remote_task_finished: (
            Callable[[RegisteredAgent, str], Awaitable[None]] | None
        ) = None,
        on_research_completed: (
            Callable[
                [RegisteredAgent, RemoteTaskResult[EvidenceBundle]],
                Awaitable[None],
            ]
            | None
        ) = None,
        on_analysis_completed: (
            Callable[
                [RegisteredAgent, RemoteTaskResult[DecisionAnalysis]],
                Awaitable[None],
            ]
            | None
        ) = None,
    ) -> WorkflowExecution: ...

    async def verify(
        self,
        evidence_bundle: EvidenceBundle,
        *,
        on_verification_scheduled: (
            Callable[[RegisteredAgent], Awaitable[None]] | None
        ) = None,
        on_remote_task_started: (
            Callable[[RegisteredAgent, str], Awaitable[None]] | None
        ) = None,
        on_remote_task_finished: (
            Callable[[RegisteredAgent, str], Awaitable[None]] | None
        ) = None,
    ) -> RemoteTaskResult[VerificationReport]: ...

    async def challenge(
        self,
        request: AnalysisRequest,
        *,
        on_remote_task_started: (
            Callable[[RegisteredAgent, str], Awaitable[None]] | None
        ) = None,
        on_remote_task_finished: (
            Callable[[RegisteredAgent, str], Awaitable[None]] | None
        ) = None,
    ) -> RemoteTaskResult[RecommendationChallenge]: ...

    async def cancel(
        self,
        *,
        agent: RegisteredAgent,
        remote_task_id: str,
        timeout_seconds: float,
    ) -> None: ...


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


class _RemoteCancellationScope:
    """Track remote work for follow-up runs that do not reopen session state."""

    def __init__(self, canceller: WorkflowRunner, *, timeout_seconds: float = 10) -> None:
        self._canceller = canceller
        self._timeout_seconds = timeout_seconds
        self._active: dict[str, RegisteredAgent] = {}
        self._cancelled = False
        self._lock = asyncio.Lock()

    async def register(self, agent: RegisteredAgent, remote_task_id: str) -> None:
        async with self._lock:
            cancel_immediately = self._cancelled
            if not cancel_immediately:
                self._active[remote_task_id] = agent
        if cancel_immediately:
            await self._cancel_one(agent, remote_task_id)

    async def complete(self, agent: RegisteredAgent, remote_task_id: str) -> None:
        del agent
        async with self._lock:
            self._active.pop(remote_task_id, None)

    async def cancel(self) -> None:
        async with self._lock:
            self._cancelled = True
            active = tuple(self._active.items())
        await asyncio.gather(
            *(
                self._cancel_one(agent, remote_task_id)
                for remote_task_id, agent in active
            )
        )

    async def _cancel_one(
        self,
        agent: RegisteredAgent,
        remote_task_id: str,
    ) -> None:
        with suppress(Exception):
            await self._canceller.cancel(
                agent=agent,
                remote_task_id=remote_task_id,
                timeout_seconds=self._timeout_seconds,
            )


class OrchestrationCommandExecutor:
    """Execute typed Coordinator commands against durable workflow services."""

    def __init__(
        self,
        *,
        planner: WorkflowPlanner,
        orchestrator: WorkflowRunner,
        persistence: WorkflowPersistenceService,
        projector: DurableAgUiProjector,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._planner = planner
        self._orchestrator = orchestrator
        self._persistence = persistence
        self._projector = projector
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self, command: CoordinatorCommand
    ) -> AsyncIterator[CoordinatorRunUpdate]:
        correlation = command.correlation
        with observed_request(
            LOGGER,
            "coordinator.command",
            CorrelationIds(
                session_id=correlation.session_id,
                context_id=correlation.thread_id,
                correlation_id=correlation.run_id,
                action_id=correlation.action_id,
                agent="coordinator",
            ),
        ):
            async for update in self._execute_command(command):
                yield update

    async def _execute_command(
        self, command: CoordinatorCommand
    ) -> AsyncIterator[CoordinatorRunUpdate]:
        if isinstance(command, ChallengeRecommendationCommand):
            async for update in self._execute_challenge(command):
                yield update
            return
        if isinstance(command, (ResearchDeeperCommand, FocusOnCriterionCommand)):
            async for update in self._execute_research_follow_up(command):
                yield update
            return
        if isinstance(command, RetryFailedAgentCommand):
            yield self._record_unsupported_follow_up(command)
            return

        machine = WorkflowStateMachine(
            command.correlation.session_id,
            clock=self._clock,
            on_transition=self._persistence.persist_transition,
        )
        cancellation = CancellationCoordinator(
            state_machine=machine,
            remote_canceller=self._orchestrator,
        )
        initialized = False
        orchestration_task: asyncio.Task[WorkflowExecution] | None = None
        verification_task: asyncio.Task[RemoteTaskResult[VerificationReport]] | None = None
        sequence = 0
        research_task_id: str | None = None
        analysis_task_id: str | None = None
        analysis_activity_id: str | None = None
        analysis_agent_id: str | None = None
        analysis_completed = False
        analysis_started = False
        verification_task_id: str | None = None
        verification_activity_id: str | None = None
        verification_agent_id: str | None = None
        verification_completed = False
        verification_started = False
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
            research_step = next(
                step for step in plan.steps if step.skill == "web-research"
            )
            analysis_step = next(
                step for step in plan.steps if step.skill == "decision-analysis"
            )
            analysis_agent_id = analysis_step.provider_agent_id
            research_task_id = _agent_task_id(
                command.correlation.session_id,
                command.correlation.run_id,
                research_step.step_id,
            )
            self._persistence.create_agent_task(
                AgentTaskRecord(
                    id=research_task_id,
                    session_id=command.correlation.session_id,
                    run_id=command.correlation.run_id,
                    agent_id=research_step.provider_agent_id,
                    skill=research_step.skill,
                    started_at=machine.snapshot.updated_at,
                )
            )
            analysis_task_id = _agent_task_id(
                command.correlation.session_id,
                command.correlation.run_id,
                analysis_step.step_id,
            )
            analysis_activity_id = f"analysis:{analysis_task_id}"
            self._persistence.create_agent_task(
                AgentTaskRecord(
                    id=analysis_task_id,
                    session_id=command.correlation.session_id,
                    run_id=command.correlation.run_id,
                    agent_id=analysis_step.provider_agent_id,
                    skill=analysis_step.skill,
                    started_at=machine.snapshot.updated_at,
                )
            )
            activity_id = f"research:{research_task_id}"
            sequence += 1
            yield CoordinatorStateUpdate(
                self._projector.snapshot(command.correlation.session_id),
                sequence=sequence,
            )
            yield CoordinatorActivityUpdate(
                message_id=activity_id,
                activity_type="specialist-research",
                agent_id=research_step.provider_agent_id,
                status="waiting",
                summary="Research specialist is waiting to start.",
            )

            updates: asyncio.Queue[CoordinatorRunUpdate] = asyncio.Queue()
            research_completed = False

            async def remote_task_started(
                agent: RegisteredAgent,
                remote_task_id: str,
            ) -> None:
                nonlocal analysis_started, sequence
                if machine.snapshot.status in TERMINAL_STATUSES | {"cancelling"}:
                    if machine.snapshot.status in {"cancelling", "cancelled"}:
                        await cancellation.register(agent, remote_task_id)
                        task_id = (
                            analysis_task_id
                            if agent.agent_id == analysis_step.provider_agent_id
                            else research_task_id
                        )
                        if task_id is not None:
                            self._persistence.register_remote_task(
                                task_id,
                                remote_task_id=remote_task_id,
                            )
                    return
                await cancellation.register(agent, remote_task_id)
                if agent.agent_id == analysis_step.provider_agent_id:
                    if analysis_completed:
                        return
                    assert analysis_task_id is not None
                    assert analysis_activity_id is not None
                    self._persistence.register_remote_task(
                        analysis_task_id,
                        remote_task_id=remote_task_id,
                    )
                    analysis_started = True
                    sequence += 1
                    await updates.put(
                        CoordinatorStepUpdate(step_name="analysis", status="started")
                    )
                    await updates.put(
                        CoordinatorActivityUpdate(
                            message_id=analysis_activity_id,
                            activity_type="specialist-analysis",
                            agent_id=agent.agent_id,
                            status="working",
                            summary="Analysis specialist is evaluating the evidence.",
                        )
                    )
                    await updates.put(
                        CoordinatorStateUpdate(
                            self._projector.snapshot(command.correlation.session_id),
                            sequence=sequence,
                        )
                    )
                    return
                if agent.agent_id != research_step.provider_agent_id or research_completed:
                    return
                self._persistence.register_remote_task(
                    research_task_id,
                    remote_task_id=remote_task_id,
                )
                sequence += 1
                await updates.put(
                    CoordinatorStepUpdate(step_name="research", status="started")
                )
                await updates.put(
                    CoordinatorActivityUpdate(
                        message_id=activity_id,
                        activity_type="specialist-research",
                        agent_id=agent.agent_id,
                        status="working",
                        summary="Research specialist is collecting evidence.",
                    )
                )
                await updates.put(
                    CoordinatorStateUpdate(
                        self._projector.snapshot(command.correlation.session_id),
                        sequence=sequence,
                    )
                )

            async def remote_task_finished(
                agent: RegisteredAgent,
                remote_task_id: str,
            ) -> None:
                del agent
                await cancellation.complete(remote_task_id)

            async def research_task_completed(
                agent: RegisteredAgent,
                result: RemoteTaskResult[EvidenceBundle],
            ) -> None:
                nonlocal research_completed, sequence
                if machine.snapshot.status in TERMINAL_STATUSES | {"cancelling"}:
                    return
                if agent.agent_id != research_step.provider_agent_id:
                    raise RuntimeError("Research result provider does not match the plan.")
                self._persistence.register_remote_task(
                    research_task_id,
                    remote_task_id=result.remote_task_id,
                    a2a_context_id=result.remote_context_id,
                )
                self._persistence.persist_evidence(
                    command.correlation.session_id,
                    research_task_id,
                    result.artifact,
                )
                if research_completed:
                    return
                finished_at = self._clock()
                self._persistence.finish_agent_task(
                    research_task_id,
                    status="completed",
                    finished_at=finished_at,
                )
                if machine.snapshot.status == "researching":
                    machine.transition(
                        "analyzing",
                        active_step="analysis",
                        completed_steps=["research"],
                    )
                research_completed = True
                sequence += 1
                await updates.put(
                    CoordinatorStateUpdate(
                        self._projector.snapshot(command.correlation.session_id),
                        sequence=sequence,
                    )
                )
                await updates.put(
                    CoordinatorActivityUpdate(
                        message_id=activity_id,
                        activity_type="specialist-research",
                        agent_id=agent.agent_id,
                        status="completed",
                        summary="Research evidence was accepted.",
                    )
                )
                await updates.put(
                    CoordinatorStepUpdate(step_name="research", status="finished")
                )
                assert analysis_activity_id is not None
                await updates.put(
                    CoordinatorActivityUpdate(
                        message_id=analysis_activity_id,
                        activity_type="specialist-analysis",
                        agent_id=analysis_step.provider_agent_id,
                        status="waiting",
                        summary="Analysis specialist is waiting for accepted evidence.",
                    )
                )

            async def analysis_task_completed(
                agent: RegisteredAgent,
                result: RemoteTaskResult[DecisionAnalysis],
            ) -> None:
                nonlocal analysis_completed, sequence
                if machine.snapshot.status in TERMINAL_STATUSES | {"cancelling"}:
                    return
                if agent.agent_id != analysis_step.provider_agent_id:
                    raise RuntimeError("Analysis result provider does not match the plan.")
                assert analysis_task_id is not None
                assert analysis_activity_id is not None
                self._persistence.register_remote_task(
                    analysis_task_id,
                    remote_task_id=result.remote_task_id,
                    a2a_context_id=result.remote_context_id,
                )
                self._persistence.persist_analysis(
                    command.correlation.session_id,
                    analysis_task_id,
                    result.artifact,
                )
                if analysis_completed:
                    return
                self._persistence.finish_agent_task(
                    analysis_task_id,
                    status="completed",
                    finished_at=self._clock(),
                )
                analysis_completed = True
                sequence += 1
                await updates.put(
                    CoordinatorStateUpdate(
                        self._projector.snapshot(command.correlation.session_id),
                        sequence=sequence,
                    )
                )
                await updates.put(
                    CoordinatorActivityUpdate(
                        message_id=analysis_activity_id,
                        activity_type="specialist-analysis",
                        agent_id=agent.agent_id,
                        status="completed",
                        summary="Decision analysis was accepted.",
                    )
                )
                await updates.put(
                    CoordinatorStepUpdate(step_name="analysis", status="finished")
                )

            async def verification_scheduled(agent: RegisteredAgent) -> None:
                nonlocal sequence
                nonlocal verification_activity_id, verification_agent_id
                nonlocal verification_task_id
                if machine.snapshot.status in TERMINAL_STATUSES | {"cancelling"}:
                    return
                if not analysis_completed or machine.snapshot.status != "analyzing":
                    raise RuntimeError(
                        "Verification cannot start before accepted decision analysis."
                    )
                verification_agent_id = agent.agent_id
                verification_task_id = _agent_task_id(
                    command.correlation.session_id,
                    command.correlation.run_id,
                    "verification",
                )
                verification_activity_id = f"verification:{verification_task_id}"
                self._persistence.create_agent_task(
                    AgentTaskRecord(
                        id=verification_task_id,
                        session_id=command.correlation.session_id,
                        run_id=command.correlation.run_id,
                        agent_id=agent.agent_id,
                        skill="fact-verification",
                        started_at=machine.snapshot.updated_at,
                    )
                )
                machine.transition(
                    "verifying",
                    active_step="verification",
                    completed_steps=["analysis"],
                )
                sequence += 1
                await updates.put(
                    CoordinatorStateUpdate(
                        self._projector.snapshot(command.correlation.session_id),
                        sequence=sequence,
                    )
                )
                await updates.put(
                    CoordinatorActivityUpdate(
                        message_id=verification_activity_id,
                        activity_type="specialist-verification",
                        agent_id=agent.agent_id,
                        status="waiting",
                        summary="Verification specialist is waiting to start.",
                    )
                )

            async def verification_remote_task_started(
                agent: RegisteredAgent,
                remote_task_id: str,
            ) -> None:
                nonlocal sequence, verification_started
                await cancellation.register(agent, remote_task_id)
                if verification_task_id is None:
                    return
                self._persistence.register_remote_task(
                    verification_task_id,
                    remote_task_id=remote_task_id,
                )
                if machine.snapshot.status in TERMINAL_STATUSES | {"cancelling"}:
                    return
                assert verification_activity_id is not None
                verification_started = True
                sequence += 1
                await updates.put(
                    CoordinatorStepUpdate(step_name="verification", status="started")
                )
                await updates.put(
                    CoordinatorActivityUpdate(
                        message_id=verification_activity_id,
                        activity_type="specialist-verification",
                        agent_id=agent.agent_id,
                        status="working",
                        summary="Verification specialist is checking every claim.",
                    )
                )
                await updates.put(
                    CoordinatorStateUpdate(
                        self._projector.snapshot(command.correlation.session_id),
                        sequence=sequence,
                    )
                )

            async def verification_remote_task_finished(
                agent: RegisteredAgent,
                remote_task_id: str,
            ) -> None:
                del agent
                await cancellation.complete(remote_task_id)

            orchestration_task = asyncio.create_task(
                self._orchestrator.execute(
                    command.request,
                    plan,
                    on_remote_task_started=remote_task_started,
                    on_remote_task_finished=remote_task_finished,
                    on_research_completed=research_task_completed,
                    on_analysis_completed=analysis_task_completed,
                )
            )
            async for update in _queued_updates(orchestration_task, updates):
                yield update
            execution = await orchestration_task
            if machine.snapshot.status == "researching":
                machine.transition(
                    "analyzing",
                    active_step="analysis",
                    completed_steps=["research"],
                )
            verification_task = asyncio.create_task(
                self._orchestrator.verify(
                    execution.research.artifact.payload,
                    on_verification_scheduled=verification_scheduled,
                    on_remote_task_started=verification_remote_task_started,
                    on_remote_task_finished=verification_remote_task_finished,
                )
            )
            async for update in _queued_updates(verification_task, updates):
                yield update
            try:
                verification_result = await verification_task
            except Exception as error:
                if verification_task_id is not None:
                    self._persistence.finish_agent_task(
                        verification_task_id,
                        status="failed",
                        finished_at=self._clock(),
                        error_code=_failure_code(error),
                        error_message=_safe_failure_message(error),
                    )
                if machine.snapshot.status == "analyzing":
                    machine.transition(
                        "partial",
                        completed_steps=["analysis"],
                        failed_steps=["verification"],
                        reason="Verification did not complete after successful analysis.",
                    )
                elif machine.snapshot.status == "verifying":
                    machine.transition(
                        "partial",
                        failed_steps=["verification"],
                        reason="Verification did not complete after successful analysis.",
                    )
                self._persistence.finish_run(
                    command.correlation.run_id,
                    status="partial",
                    finished_at=machine.snapshot.updated_at,
                )
                sequence += 1
                yield CoordinatorStateUpdate(
                    self._projector.snapshot(command.correlation.session_id),
                    sequence=sequence,
                )
                if verification_activity_id is not None:
                    yield CoordinatorActivityUpdate(
                        message_id=verification_activity_id,
                        activity_type="specialist-verification",
                        agent_id=verification_agent_id or "verifier",
                        status="failed",
                        summary="Claim verification did not complete.",
                    )
                if verification_started:
                    yield CoordinatorStepUpdate(
                        step_name="verification",
                        status="finished",
                    )
                yield CoordinatorRunOutcome(
                    status="partial",
                    message=(
                        "Research and analysis remain available, but verification "
                        "did not complete."
                    ),
                    remote_tasks=(
                        _remote_correlation(execution.research),
                        _remote_correlation(execution.analysis),
                    ),
                )
                return

            if verification_task_id is None:
                raise RuntimeError("Verification completed without a durable task.")
            self._persistence.register_remote_task(
                verification_task_id,
                remote_task_id=verification_result.remote_task_id,
                a2a_context_id=verification_result.remote_context_id,
            )
            self._persistence.persist_verification_report(
                command.correlation.session_id,
                verification_task_id,
                verification_result.artifact,
            )
            self._persistence.finish_agent_task(
                verification_task_id,
                status="completed",
                finished_at=self._clock(),
            )
            verification_completed = True
            machine.transition("completed", completed_steps=["verification"])
            self._persistence.finish_run(
                command.correlation.run_id,
                status="completed",
                finished_at=machine.snapshot.updated_at,
            )
            sequence += 1
            yield CoordinatorStateUpdate(
                self._projector.snapshot(command.correlation.session_id),
                sequence=sequence,
            )
            assert verification_activity_id is not None
            yield CoordinatorActivityUpdate(
                message_id=verification_activity_id,
                activity_type="specialist-verification",
                agent_id=verification_agent_id or "verifier",
                status="completed",
                summary="Claim verification was accepted.",
            )
            yield CoordinatorStepUpdate(step_name="verification", status="finished")
        except asyncio.CancelledError:
            if initialized and machine.snapshot.status not in TERMINAL_STATUSES:
                await cancellation.cancel("The browser cancelled the Coordinator run.")
                self._persistence.cancel_run_agent_tasks(
                    session_id=command.correlation.session_id,
                    run_id=command.correlation.run_id,
                    finished_at=machine.snapshot.updated_at,
                )
                self._persistence.finish_run(
                    command.correlation.run_id,
                    status="cancelled",
                    finished_at=machine.snapshot.updated_at,
                )
            if orchestration_task is not None and not orchestration_task.done():
                orchestration_task.cancel()
                with suppress(asyncio.CancelledError):
                    await orchestration_task
            if verification_task is not None and not verification_task.done():
                verification_task.cancel()
                with suppress(asyncio.CancelledError):
                    await verification_task
            raise
        except Exception as error:
            terminal_status = "failed"
            if initialized:
                if (
                    analysis_task_id is not None
                    and machine.snapshot.status == "analyzing"
                    and not analysis_completed
                ):
                    self._persistence.finish_agent_task(
                        analysis_task_id,
                        status="failed",
                        finished_at=self._clock(),
                        error_code=_failure_code(error),
                        error_message=_safe_failure_message(error),
                    )
                if (
                    verification_task_id is not None
                    and machine.snapshot.status == "verifying"
                    and not verification_completed
                ):
                    self._persistence.finish_agent_task(
                        verification_task_id,
                        status="failed",
                        finished_at=self._clock(),
                        error_code=_failure_code(error),
                        error_message=_safe_failure_message(error),
                    )
                terminal_status = self._fail_run(command, machine)
                sequence += 1
                yield CoordinatorStateUpdate(
                    self._projector.snapshot(command.correlation.session_id),
                    sequence=sequence,
                )
                if (
                    terminal_status == "partial"
                    and verification_task_id is not None
                    and analysis_completed
                    and not verification_completed
                ):
                    if verification_activity_id is not None:
                        yield CoordinatorActivityUpdate(
                            message_id=verification_activity_id,
                            activity_type="specialist-verification",
                            agent_id=verification_agent_id or "verifier",
                            status="failed",
                            summary="Claim verification did not complete.",
                        )
                    if verification_started:
                        yield CoordinatorStepUpdate(
                            step_name="verification",
                            status="finished",
                        )
                    yield CoordinatorRunOutcome(
                        status="partial",
                        message=(
                            "Research and analysis remain available, but verification "
                            "did not complete."
                        ),
                        remote_tasks=(
                            _remote_correlation(execution.research),
                            _remote_correlation(execution.analysis),
                        ),
                    )
                    return
                if terminal_status == "partial" and analysis_activity_id is not None:
                    yield CoordinatorActivityUpdate(
                        message_id=analysis_activity_id,
                        activity_type="specialist-analysis",
                        agent_id=analysis_agent_id or "analyst",
                        status="failed",
                        summary="Decision analysis did not complete.",
                    )
                    if analysis_started:
                        yield CoordinatorStepUpdate(
                            step_name="analysis",
                            status="finished",
                        )
                    yield CoordinatorRunOutcome(
                        status="partial",
                        message=(
                            "Research evidence remains available, but analysis did not "
                            "complete."
                        ),
                    )
                    return
            yield CoordinatorRunOutcome(
                status="failed",
                message=_safe_failure_message(error),
                error_code=_failure_code(error),
            )
            return

        yield CoordinatorRunOutcome(
            status="completed",
            message="Research, analysis, and verification completed.",
            remote_tasks=(
                _remote_correlation(execution.research),
                _remote_correlation(execution.analysis),
                _remote_correlation(verification_result),
            ),
        )

    async def _execute_challenge(
        self,
        command: ChallengeRecommendationCommand,
    ) -> AsyncIterator[CoordinatorRunUpdate]:
        started_at = self._clock()
        initialized = False
        activity_id = f"challenge:{command.correlation.run_id}"
        remote_scope = _RemoteCancellationScope(self._orchestrator)
        challenge_task: asyncio.Task[RemoteTaskResult[RecommendationChallenge]] | None = None
        try:
            self._continue_follow_up(command, started_at)
            initialized = True
            context = self._persistence.load_follow_up_context(
                command.correlation.session_id
            )
            request = AnalysisRequest(
                question=context.question,
                options=list(context.options),
                criteria=list(context.criteria),
                evidence_bundle=context.evidence_bundle,
                mode="challenge_current_recommendation",
                current_recommendation=context.current_recommendation,
            )
            yield CoordinatorActivityUpdate(
                message_id=activity_id,
                activity_type="specialist-counteranalysis",
                agent_id="analyst",
                status="waiting",
                summary="Analyst is preparing a counteranalysis.",
            )
            challenge_task = asyncio.create_task(
                self._orchestrator.challenge(
                    request,
                    on_remote_task_started=remote_scope.register,
                    on_remote_task_finished=remote_scope.complete,
                )
            )
            result = await asyncio.shield(challenge_task)
            task_id = _agent_task_id(
                command.correlation.session_id,
                command.correlation.run_id,
                "challenge-recommendation",
            )
            finished_at = self._clock()
            self._persistence.create_agent_task(
                AgentTaskRecord(
                    id=task_id,
                    session_id=command.correlation.session_id,
                    run_id=command.correlation.run_id,
                    agent_id=result.agent_id,
                    skill="decision-analysis",
                    a2a_context_id=result.remote_context_id,
                    remote_task_id=result.remote_task_id,
                    status="completed",
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )
            self._persistence.persist_recommendation_challenge(
                command.correlation.session_id,
                task_id,
                result.artifact,
            )
            self._persistence.finish_run(
                command.correlation.run_id,
                status="completed",
                finished_at=finished_at,
            )
            yield CoordinatorStateUpdate(
                self._projector.snapshot(command.correlation.session_id),
                sequence=1,
            )
            yield CoordinatorActivityUpdate(
                message_id=activity_id,
                activity_type="specialist-counteranalysis",
                agent_id=result.agent_id,
                status="completed",
                summary="Counteranalysis was accepted.",
            )
        except asyncio.CancelledError:
            await remote_scope.cancel()
            if challenge_task is not None and not challenge_task.done():
                challenge_task.cancel()
                with suppress(asyncio.CancelledError):
                    await challenge_task
            if initialized:
                self._finish_follow_up_run(command, "cancelled")
            raise
        except Exception as error:
            if initialized:
                self._finish_follow_up_run(command, "failed")
            yield CoordinatorRunOutcome(
                status="failed",
                message=_safe_follow_up_message(error),
                error_code=_failure_code(error),
            )
            return
        yield CoordinatorRunOutcome(
            status="completed",
            message="Recommendation counteranalysis completed.",
            remote_tasks=(_remote_correlation(result),),
        )

    async def _execute_research_follow_up(
        self,
        command: ResearchDeeperCommand | FocusOnCriterionCommand,
    ) -> AsyncIterator[CoordinatorRunUpdate]:
        started_at = self._clock()
        initialized = False
        activity_id = f"follow-up:{command.correlation.run_id}"
        remote_scope = _RemoteCancellationScope(self._orchestrator)
        orchestration_task: asyncio.Task[WorkflowExecution] | None = None
        try:
            self._continue_follow_up(command, started_at)
            initialized = True
            context = self._persistence.load_follow_up_context(
                command.correlation.session_id
            )
            if isinstance(command, ResearchDeeperCommand):
                criteria = list(command.focus_areas or context.criteria)
                desired_depth = command.desired_depth
            else:
                criterion = next(
                    (
                        item
                        for item in context.criteria
                        if item.casefold() == command.criterion.casefold()
                    ),
                    command.criterion,
                )
                criteria = [criterion]
                desired_depth = "deep"
            request = ResearchRequest(
                question=context.question,
                options=list(context.options),
                criteria=criteria,
                desired_depth=desired_depth,
            )
            yield CoordinatorActivityUpdate(
                message_id=activity_id,
                activity_type="specialist-follow-up",
                agent_id="coordinator",
                status="waiting",
                summary="Follow-up research and analysis are queued.",
            )
            plan = await self._planner.plan(request)
            orchestration_task = asyncio.create_task(
                self._orchestrator.execute(
                    request,
                    plan,
                    on_remote_task_started=remote_scope.register,
                    on_remote_task_finished=remote_scope.complete,
                )
            )
            execution = await asyncio.shield(orchestration_task)
            finished_at = self._clock()
            research_step = next(
                step for step in plan.steps if step.skill == "web-research"
            )
            analysis_step = next(
                step for step in plan.steps if step.skill == "decision-analysis"
            )
            research_task_id = _agent_task_id(
                command.correlation.session_id,
                command.correlation.run_id,
                research_step.step_id,
            )
            analysis_task_id = _agent_task_id(
                command.correlation.session_id,
                command.correlation.run_id,
                analysis_step.step_id,
            )
            for task_id, step, result in (
                (research_task_id, research_step, execution.research),
                (analysis_task_id, analysis_step, execution.analysis),
            ):
                self._persistence.create_agent_task(
                    AgentTaskRecord(
                        id=task_id,
                        session_id=command.correlation.session_id,
                        run_id=command.correlation.run_id,
                        agent_id=result.agent_id,
                        skill=step.skill,
                        a2a_context_id=result.remote_context_id,
                        remote_task_id=result.remote_task_id,
                        status="completed",
                        started_at=started_at,
                        finished_at=finished_at,
                    )
                )
            self._persistence.persist_evidence(
                command.correlation.session_id,
                research_task_id,
                execution.research.artifact,
            )
            self._persistence.persist_analysis(
                command.correlation.session_id,
                analysis_task_id,
                execution.analysis.artifact,
            )
            self._persistence.finish_run(
                command.correlation.run_id,
                status="completed",
                finished_at=finished_at,
            )
            yield CoordinatorStateUpdate(
                self._projector.snapshot(command.correlation.session_id),
                sequence=1,
            )
            yield CoordinatorActivityUpdate(
                message_id=activity_id,
                activity_type="specialist-follow-up",
                agent_id="coordinator",
                status="completed",
                summary="Follow-up research and analysis were accepted.",
            )
        except asyncio.CancelledError:
            await remote_scope.cancel()
            if orchestration_task is not None and not orchestration_task.done():
                orchestration_task.cancel()
                with suppress(asyncio.CancelledError):
                    await orchestration_task
            if initialized:
                self._finish_follow_up_run(command, "cancelled")
            raise
        except Exception as error:
            if initialized:
                self._finish_follow_up_run(command, "failed")
            yield CoordinatorRunOutcome(
                status="failed",
                message=_safe_follow_up_message(error),
                error_code=_failure_code(error),
            )
            return
        yield CoordinatorRunOutcome(
            status="completed",
            message="Follow-up research and analysis completed.",
            remote_tasks=(
                _remote_correlation(execution.research),
                _remote_correlation(execution.analysis),
            ),
        )

    def _continue_follow_up(
        self,
        command: ChallengeRecommendationCommand
        | ResearchDeeperCommand
        | FocusOnCriterionCommand,
        started_at: datetime,
    ) -> None:
        self._persistence.continue_session(
            session_id=command.correlation.session_id,
            ag_ui_thread_id=command.correlation.thread_id,
            run_id=command.correlation.run_id,
            action_id=command.correlation.action_id,
            action_type=_action_type(command),
            started_at=started_at,
        )
        self._persistence.start_run(command.correlation.run_id)

    def _finish_follow_up_run(
        self,
        command: ChallengeRecommendationCommand
        | ResearchDeeperCommand
        | FocusOnCriterionCommand,
        status: Literal["failed", "cancelled"],
    ) -> None:
        with suppress(WorkflowPersistenceError):
            self._persistence.finish_run(
                command.correlation.run_id,
                status=status,
                finished_at=self._clock(),
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

    def _fail_run(
        self,
        command: StartResearchCommand,
        machine: WorkflowStateMachine,
    ) -> Literal["failed", "partial"]:
        terminal_status: Literal["failed", "partial"] = "failed"
        if machine.snapshot.status not in TERMINAL_STATUSES:
            if (
                machine.snapshot.status == "analyzing"
                and "research" in machine.snapshot.completed_steps
            ):
                terminal_status = "partial"
                machine.transition(
                    "partial",
                    failed_steps=["analysis"],
                    reason="Analysis did not complete after successful research.",
                )
            elif (
                machine.snapshot.status == "verifying"
                and "analysis" in machine.snapshot.completed_steps
            ):
                terminal_status = "partial"
                machine.transition(
                    "partial",
                    failed_steps=["verification"],
                    reason="Verification did not complete after successful analysis.",
                )
            else:
                active_step = machine.snapshot.active_step
                machine.transition(
                    "failed",
                    failed_steps=([active_step] if active_step is not None else []),
                    reason="Coordinator orchestration failed.",
                )
        try:
            self._persistence.finish_run(
                command.correlation.run_id,
                status=terminal_status,
                finished_at=machine.snapshot.updated_at,
            )
        except WorkflowPersistenceError:
            # Initialization itself can fail before a durable run exists.
            return terminal_status
        return terminal_status


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
        projector=DurableAgUiProjector(database),
    )


async def _queued_updates[ResultT](
    orchestration_task: asyncio.Task[ResultT],
    updates: asyncio.Queue[CoordinatorRunUpdate],
) -> AsyncIterator[CoordinatorRunUpdate]:
    while not orchestration_task.done() or not updates.empty():
        if not updates.empty():
            yield updates.get_nowait()
            continue
        pending_update = asyncio.create_task(updates.get())
        done, _ = await asyncio.wait(
            {orchestration_task, pending_update},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if pending_update in done:
            yield pending_update.result()
            continue
        pending_update.cancel()
        with suppress(asyncio.CancelledError):
            await pending_update


def _agent_task_id(session_id: str, run_id: str, step_id: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"agentdesk:{session_id}:run:{run_id}:step:{step_id}",
        )
    )


def _remote_correlation(
    result: RemoteTaskResult[EvidenceBundle]
    | RemoteTaskResult[DecisionAnalysis]
    | RemoteTaskResult[RecommendationChallenge]
    | RemoteTaskResult[VerificationReport],
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


def _safe_follow_up_message(error: Exception) -> str:
    if isinstance(error, (RepositoryError, WorkflowPersistenceError)):
        return "The requested Coordinator session could not be continued."
    return _safe_failure_message(error)


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
