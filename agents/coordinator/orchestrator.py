"""UI-neutral Research-to-Analyst workflow execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from agents.coordinator.a2a_client import A2AClientAdapter, RemoteTaskResult
from agents.coordinator.planner import PlannedStep, WorkflowPlan
from agents.coordinator.registry import AgentRegistry, RegisteredAgent
from packages.contracts import AnalysisRequest, DecisionAnalysis, EvidenceBundle, ResearchRequest


class RemoteAgentClient(Protocol):
    async def execute[PayloadT: BaseModel](
        self,
        *,
        agent: RegisteredAgent,
        request: BaseModel,
        artifact_name: str,
        payload_model: type[PayloadT],
        timeout_seconds: float,
    ) -> RemoteTaskResult[PayloadT]: ...


class OrchestrationPlanError(RuntimeError):
    """Raised before remote work when the executable plan is inconsistent."""


@dataclass(frozen=True)
class WorkflowExecution:
    """Completed specialist results with preserved remote task identity."""

    research: RemoteTaskResult[EvidenceBundle]
    analysis: RemoteTaskResult[DecisionAnalysis]


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
        research_result = await self._remote_client.execute(
            agent=research_agent,
            request=research_request,
            artifact_name="evidence-bundle",
            payload_model=EvidenceBundle,
            timeout_seconds=self._step_timeout_seconds,
        )
        analysis_request = AnalysisRequest(
            question=request.question,
            options=request.options,
            constraints=request.constraints,
            criteria=plan.criteria,
            evidence_bundle=research_result.artifact.payload,
        )
        analysis_result = await self._remote_client.execute(
            agent=analysis_agent,
            request=analysis_request,
            artifact_name="decision-analysis",
            payload_model=DecisionAnalysis,
            timeout_seconds=self._step_timeout_seconds,
        )
        return WorkflowExecution(research=research_result, analysis=analysis_result)

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
