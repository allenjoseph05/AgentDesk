"""Runnable Coordinator configured for the deterministic fixture demo."""

from __future__ import annotations

import asyncio
import os

from pydantic import AnyHttpUrl

from agents.coordinator.main import create_app
from agents.coordinator.planner import PlannedStep, PlanningFailedError, WorkflowPlan
from agents.coordinator.registry import AgentRegistry
from packages.contracts import ResearchRequest
from packages.testing import load_research_fixture

DEFAULT_FIXTURE_ID = "postgresql-vs-mongodb-golden"


class FixtureWorkflowPlanner:
    """Resolve one fixed fixture workflow without contacting an external LLM."""

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        fixture_id: str = DEFAULT_FIXTURE_ID,
        planning_delay_seconds: float = 0,
    ) -> None:
        if planning_delay_seconds < 0:
            raise ValueError("Fixture planning delay cannot be negative.")
        fixture = load_research_fixture(fixture_id)
        if not fixture.golden:
            raise ValueError("Coordinator demo mode requires a golden fixture.")
        self._registry = registry
        self._request = fixture.request
        self._planning_delay_seconds = planning_delay_seconds

    async def plan(self, request: ResearchRequest) -> WorkflowPlan:
        validated_request = ResearchRequest.model_validate(request.model_dump(mode="python"))
        if validated_request != self._request:
            raise PlanningFailedError(
                "fixture_request_mismatch",
                "Fixture demo mode accepts only its displayed deterministic request.",
                attempts=0,
            )
        if self._planning_delay_seconds:
            await asyncio.sleep(self._planning_delay_seconds)

        researcher = self._registry.first_by_skill("web-research")
        analyst = self._registry.first_by_skill("decision-analysis")
        if researcher is None or analyst is None:
            raise PlanningFailedError(
                "fixture_agent_unavailable",
                "Fixture demo specialists are not ready.",
                attempts=0,
            )
        research_step_id = "research-evidence"
        return WorkflowPlan(
            goal="compare_options",
            criteria=self._request.criteria,
            steps=[
                PlannedStep(
                    step_id=research_step_id,
                    skill="web-research",
                    scope="Retrieve the deterministic comparison evidence fixture.",
                    provider_agent_id=researcher.agent_id,
                    provider_base_url=AnyHttpUrl(researcher.base_url),
                ),
                PlannedStep(
                    step_id="decision-analysis",
                    skill="decision-analysis",
                    scope="Analyze the deterministic evidence fixture.",
                    depends_on=[research_step_id],
                    provider_agent_id=analyst.agent_id,
                    provider_base_url=AnyHttpUrl(analyst.base_url),
                ),
            ],
        )


_fixture_id = os.getenv("AGENTDESK_DEMO_FIXTURE_ID", DEFAULT_FIXTURE_ID)
_planning_delay = float(os.getenv("AGENTDESK_DEMO_PLANNING_DELAY_SECONDS", "0"))
app = create_app(
    planner_factory=lambda registry: FixtureWorkflowPlanner(
        registry,
        fixture_id=_fixture_id,
        planning_delay_seconds=_planning_delay,
    )
)
