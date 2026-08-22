"""Typed, registry-bound planning for the Coordinator workflow."""

from __future__ import annotations

import json
from functools import partial
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator

from agents.coordinator.registry import AgentRegistry
from packages.contracts import ResearchRequest
from packages.contracts.base import ContractModel, NonEmptyText
from packages.limits import LimitSettings, RequestBudget
from packages.llm import LLMProvider, LLMProviderError, Message
from packages.resilience import OperationPolicy, OperationTimeoutError, run_with_policy

PLANNER_PROMPT = """You plan the fixed AgentDesk compare-options workflow.
Return only the requested PlanDraft structure. Produce exactly one web-research step and one
decision-analysis step. The analysis step must depend on the research step. Use only skills listed
in registered_capabilities. Never output a service URL or invent an agent. Preserve all explicitly
supplied criteria; if none are supplied, choose concise decision criteria from the user's question
and constraints. Do not perform research or analysis in the plan and do not reveal chain-of-thought.
"""

REQUIRED_WORKFLOW_SKILLS = ("web-research", "decision-analysis")
DEFAULT_PLANNER_ATTEMPT_TIMEOUT_SECONDS = 30.0


class PlanDraftStep(ContractModel):
    """One provider-neutral step proposed by the planner model."""

    step_id: NonEmptyText
    skill: NonEmptyText
    scope: NonEmptyText
    depends_on: list[NonEmptyText] = Field(default_factory=list)


class PlanDraft(ContractModel):
    """Strict model output before providers are resolved from the registry."""

    goal: Literal["compare_options"]
    criteria: list[NonEmptyText] = Field(min_length=1)
    steps: list[PlanDraftStep] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_step_graph(self) -> PlanDraft:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Plan step IDs must be unique.")
        known_steps = set(step_ids)
        for step in self.steps:
            dependencies = step.depends_on
            if len(dependencies) != len(set(dependencies)):
                raise ValueError(f"Plan step {step.step_id} repeats a dependency.")
            if step.step_id in dependencies:
                raise ValueError(f"Plan step {step.step_id} cannot depend on itself.")
            unknown = set(dependencies) - known_steps
            if unknown:
                raise ValueError(
                    f"Plan step {step.step_id} has unknown dependencies: {sorted(unknown)}"
                )
        _reject_dependency_cycles(self.steps)
        return self


class PlannedStep(PlanDraftStep):
    """A validated plan step bound to one registered provider."""

    provider_agent_id: NonEmptyText
    provider_base_url: AnyHttpUrl


class WorkflowPlan(ContractModel):
    """Executable Coordinator plan with registry-derived provider assignments."""

    goal: Literal["compare_options"]
    criteria: list[NonEmptyText] = Field(min_length=1)
    steps: list[PlannedStep] = Field(min_length=2)


class PlannerValidationError(RuntimeError):
    """One retryable semantic failure in a typed plan draft."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PlanningFailedError(RuntimeError):
    """Raised after the bounded planner attempt budget is exhausted."""

    def __init__(self, code: str, message: str, *, attempts: int) -> None:
        self.code = code
        self.attempts = attempts
        super().__init__(message)


class DecisionPlanner:
    """Generate a typed draft and resolve all provider identity through the registry."""

    def __init__(
        self,
        *,
        llm_provider: LLMProvider,
        registry: AgentRegistry,
        max_attempts: int = 2,
        attempt_timeout_seconds: float = DEFAULT_PLANNER_ATTEMPT_TIMEOUT_SECONDS,
        limit_settings: LimitSettings | None = None,
    ) -> None:
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("Planner max_attempts must be between 1 and 5.")
        self._llm_provider = llm_provider
        self._registry = registry
        self._max_attempts = max_attempts
        self._attempt_policy = OperationPolicy(timeout_seconds=attempt_timeout_seconds)
        self._limit_settings = limit_settings or LimitSettings.from_environment()

    async def plan(self, request: ResearchRequest) -> WorkflowPlan:
        """Return an executable plan or one bounded, typed failure."""
        validated_request = ResearchRequest.model_validate(request.model_dump(mode="python"))
        if len(validated_request.options) < 2:
            raise PlanningFailedError(
                "insufficient_options",
                "Planning requires at least two named options.",
                attempts=0,
            )

        last_error_code = "invalid_plan"
        budget = RequestBudget(self._limit_settings)
        for attempt in range(1, self._max_attempts + 1):
            context = _planner_context(
                validated_request,
                self._registry,
                validation_feedback=(last_error_code if attempt > 1 else None),
            )
            try:
                budget.consume_llm()
                draft = await run_with_policy(
                    "planner.generate",
                    partial(
                        self._llm_provider.generate_structured,
                        system_prompt=PLANNER_PROMPT,
                        messages=[
                            Message(
                                role="user",
                                content=context,
                            )
                        ],
                        response_model=PlanDraft,
                    ),
                    policy=self._attempt_policy,
                )
                return _resolve_plan(validated_request, draft, self._registry)
            except PlannerValidationError as error:
                last_error_code = error.code
            except LLMProviderError:
                last_error_code = "provider_output_invalid"
            except OperationTimeoutError:
                last_error_code = "provider_timeout"

        raise PlanningFailedError(
            "attempts_exhausted",
            f"Planner did not produce a valid plan ({last_error_code}).",
            attempts=self._max_attempts,
        )


def _planner_context(
    request: ResearchRequest,
    registry: AgentRegistry,
    *,
    validation_feedback: str | None,
) -> str:
    capabilities = [
        {
            "agent_id": agent.agent_id,
            "skills": [skill.id for skill in agent.card.skills],
        }
        for agent in registry.agents
    ]
    return json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "registered_capabilities": capabilities,
            "validation_feedback": validation_feedback,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _resolve_plan(
    request: ResearchRequest,
    draft: PlanDraft,
    registry: AgentRegistry,
) -> WorkflowPlan:
    normalized_criteria = [criterion.casefold() for criterion in draft.criteria]
    if len(normalized_criteria) != len(set(normalized_criteria)):
        raise PlannerValidationError("duplicate_criteria", "Plan criteria must be unique.")
    if request.criteria and draft.criteria != request.criteria:
        raise PlannerValidationError(
            "criteria_mismatch",
            "Plan must preserve explicitly supplied criteria.",
        )

    skills = [step.skill for step in draft.steps]
    if sorted(skills) != sorted(REQUIRED_WORKFLOW_SKILLS):
        raise PlannerValidationError(
            "workflow_skills_mismatch",
            "Plan must contain exactly the required research and analysis skills.",
        )
    steps_by_skill = {step.skill: step for step in draft.steps}
    research_step = steps_by_skill["web-research"]
    analysis_step = steps_by_skill["decision-analysis"]
    if analysis_step.depends_on != [research_step.step_id]:
        raise PlannerValidationError(
            "analysis_dependency_missing",
            "Decision analysis must depend directly on the research step.",
        )
    if research_step.depends_on:
        raise PlannerValidationError(
            "research_dependency_invalid",
            "The research step cannot depend on later workflow work.",
        )

    resolved_steps: list[PlannedStep] = []
    for step in draft.steps:
        provider = registry.first_by_skill(step.skill)
        if provider is None:
            raise PlannerValidationError(
                "skill_unavailable",
                f"No healthy registered provider advertises {step.skill}.",
            )
        resolved_steps.append(
            PlannedStep.model_validate(
                {
                    **step.model_dump(),
                    "provider_agent_id": provider.agent_id,
                    "provider_base_url": provider.base_url,
                }
            )
        )
    return WorkflowPlan(
        goal=draft.goal,
        criteria=draft.criteria,
        steps=resolved_steps,
    )


def _reject_dependency_cycles(steps: list[PlanDraftStep]) -> None:
    dependencies = {step.step_id: step.depends_on for step in steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise ValueError("Plan dependencies must not contain a cycle.")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in dependencies[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in dependencies:
        visit(step_id)
