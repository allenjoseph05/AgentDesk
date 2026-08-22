"""UI-neutral Research-to-Analyst workflow execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from agents.coordinator.a2a_client import A2AClientAdapter, RemoteTaskResult
from agents.coordinator.planner import PlannedStep, WorkflowPlan
from agents.coordinator.registry import AgentRegistry, RegisteredAgent
from packages.contracts import (
    AnalysisRequest,
    DecisionAnalysis,
    EvidenceBundle,
    RecommendationChallenge,
    ResearchRequest,
)


class RemoteAgentClient(Protocol):
    async def execute[PayloadT: BaseModel](
        self,
        *,
        agent: RegisteredAgent,
        request: BaseModel,
        artifact_name: str,
        payload_model: type[PayloadT],
        timeout_seconds: float,
        on_task_started: Callable[[str], Awaitable[None]] | None = None,
    ) -> RemoteTaskResult[PayloadT]: ...

    async def cancel(
        self,
        *,
        agent: RegisteredAgent,
        remote_task_id: str,
        timeout_seconds: float,
    ) -> None: ...


class OrchestrationPlanError(RuntimeError):
    """Raised before remote work when the executable plan is inconsistent."""


@dataclass(frozen=True)
class WorkflowExecution:
    """Completed specialist results with preserved remote task identity."""

    research: RemoteTaskResult[EvidenceBundle]
    analysis: RemoteTaskResult[DecisionAnalysis]


RemoteTaskLifecycleHandler = Callable[[RegisteredAgent, str], Awaitable[None]]
ResearchCompletedHandler = Callable[
    [RegisteredAgent, RemoteTaskResult[EvidenceBundle]],
    Awaitable[None],
]
AnalysisCompletedHandler = Callable[
    [RegisteredAgent, RemoteTaskResult[DecisionAnalysis]],
    Awaitable[None],
]


class WorkflowOrchestrator:
    """Execute specialist dependencies without any UI projection logic."""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        remote_client: RemoteAgentClient | None = None,
        step_timeout_seconds: float = 30,
    ) -> None:
        if step_timeout_seconds <= 0:
            raise ValueError("Orchestrator step timeout must be positive.")
        self._registry = registry
        self._remote_client = remote_client or A2AClientAdapter()
        self._step_timeout_seconds = step_timeout_seconds

    async def execute(
        self,
        request: ResearchRequest,
        plan: WorkflowPlan,
        *,
        on_remote_task_started: RemoteTaskLifecycleHandler | None = None,
        on_remote_task_finished: RemoteTaskLifecycleHandler | None = None,
        on_research_completed: ResearchCompletedHandler | None = None,
        on_analysis_completed: AnalysisCompletedHandler | None = None,
    ) -> WorkflowExecution:
        """Run research to completion before constructing the analysis request."""
        steps = {step.skill: step for step in plan.steps}
        try:
            research_step = steps["web-research"]
            analysis_step = steps["decision-analysis"]
        except KeyError as error:
            raise OrchestrationPlanError("Plan is missing a required specialist step.") from error
        if analysis_step.depends_on != [research_step.step_id]:
            raise OrchestrationPlanError("Analysis must depend directly on research.")

        research_agent = self._registered_provider(research_step)
        analysis_agent = self._registered_provider(analysis_step)
        research_request = request.model_copy(update={"criteria": plan.criteria}, deep=True)
        research_result = await self._execute_remote(
            agent=research_agent,
            request=research_request,
            artifact_name="evidence-bundle",
            payload_model=EvidenceBundle,
            on_remote_task_started=on_remote_task_started,
            on_remote_task_finished=on_remote_task_finished,
        )
        if on_research_completed is not None:
            await on_research_completed(research_agent, research_result)
        analysis_request = AnalysisRequest(
            question=request.question,
            options=request.options,
            constraints=request.constraints,
            criteria=plan.criteria,
            evidence_bundle=research_result.artifact.payload,
        )
        analysis_result = await self._execute_remote(
            agent=analysis_agent,
            request=analysis_request,
            artifact_name="decision-analysis",
            payload_model=DecisionAnalysis,
            on_remote_task_started=on_remote_task_started,
            on_remote_task_finished=on_remote_task_finished,
        )
        if on_analysis_completed is not None:
            await on_analysis_completed(analysis_agent, analysis_result)
        return WorkflowExecution(research=research_result, analysis=analysis_result)

    async def challenge(
        self,
        request: AnalysisRequest,
        *,
        on_remote_task_started: RemoteTaskLifecycleHandler | None = None,
        on_remote_task_finished: RemoteTaskLifecycleHandler | None = None,
    ) -> RemoteTaskResult[RecommendationChallenge]:
        """Ask the registered analyst for the strongest bounded counteranalysis."""
        agent = self._registry.first_by_skill("decision-analysis")
        if agent is None:
            raise OrchestrationPlanError(
                "No healthy provider advertises decision-analysis."
            )
        return await self._execute_remote(
            agent=agent,
            request=request,
            artifact_name="recommendation-challenge",
            payload_model=RecommendationChallenge,
            on_remote_task_started=on_remote_task_started,
            on_remote_task_finished=on_remote_task_finished,
        )

    async def cancel(
        self,
        *,
        agent: RegisteredAgent,
        remote_task_id: str,
        timeout_seconds: float,
    ) -> None:
        """Propagate a Coordinator cancellation through the A2A client boundary."""
        await self._remote_client.cancel(
            agent=agent,
            remote_task_id=remote_task_id,
            timeout_seconds=timeout_seconds,
        )

    async def _execute_remote[PayloadT: BaseModel](
        self,
        *,
        agent: RegisteredAgent,
        request: BaseModel,
        artifact_name: str,
        payload_model: type[PayloadT],
        on_remote_task_started: RemoteTaskLifecycleHandler | None,
        on_remote_task_finished: RemoteTaskLifecycleHandler | None,
    ) -> RemoteTaskResult[PayloadT]:
        remote_task_id: str | None = None

        async def task_started(task_id: str) -> None:
            nonlocal remote_task_id
            remote_task_id = task_id
            if on_remote_task_started is not None:
                await on_remote_task_started(agent, task_id)

        try:
            return await self._remote_client.execute(
                agent=agent,
                request=request,
                artifact_name=artifact_name,
                payload_model=payload_model,
                timeout_seconds=self._step_timeout_seconds,
                on_task_started=task_started,
            )
        finally:
            if remote_task_id is not None and on_remote_task_finished is not None:
                await on_remote_task_finished(agent, remote_task_id)

    def _registered_provider(self, step: PlannedStep) -> RegisteredAgent:
        provider = self._registry.get(step.provider_agent_id)
        if provider is None:
            raise OrchestrationPlanError(
                f"Planned provider {step.provider_agent_id} is not registered."
            )
        if provider.base_url != str(step.provider_base_url).rstrip("/"):
            raise OrchestrationPlanError("Planned provider URL no longer matches the registry.")
        if step.skill not in {skill.id for skill in provider.card.skills}:
            raise OrchestrationPlanError(
                f"Planned provider no longer advertises {step.skill}."
            )
        return provider
