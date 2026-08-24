"""Unit tests for deterministic Coordinator fixture planning."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest

from agents.analyst.agent_card import create_agent_card as create_analyst_card
from agents.coordinator.fixture_app import FixtureWorkflowPlanner
from agents.coordinator.planner import PlanningFailedError
from agents.coordinator.registry import AgentRegistry, RegisteredAgent
from agents.researcher.agent_card import create_agent_card as create_researcher_card
from packages.contracts import ResearchRequest
from packages.testing import load_research_fixture


class StubRegistry:
    def __init__(self) -> None:
        self._providers = {
            "web-research": RegisteredAgent(
                agent_id="researcher",
                base_url="http://researcher:8005",
                card=create_researcher_card("http://researcher:8005"),
            ),
            "decision-analysis": RegisteredAgent(
                agent_id="analyst",
                base_url="http://analyst:8006",
                card=create_analyst_card("http://analyst:8006"),
            ),
        }

    def first_by_skill(self, skill_id: str) -> RegisteredAgent | None:
        return self._providers.get(skill_id)


def test_fixture_planner_returns_one_fixed_registry_bound_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_delay)
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    planner = FixtureWorkflowPlanner(
        cast(AgentRegistry, StubRegistry()),
        planning_delay_seconds=0.35,
    )

    plan = asyncio.run(planner.plan(fixture.request))

    assert delays == [0.35]
    assert plan.criteria == fixture.request.criteria
    assert [step.skill for step in plan.steps] == ["web-research", "decision-analysis"]
    assert [step.provider_agent_id for step in plan.steps] == ["researcher", "analyst"]
    assert plan.steps[1].depends_on == [plan.steps[0].step_id]


def test_fixture_planner_rejects_requests_outside_the_displayed_scenario() -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    planner = FixtureWorkflowPlanner(cast(AgentRegistry, StubRegistry()))
    other_request = ResearchRequest.model_validate(
        {**fixture.request.model_dump(), "question": "Use a different scenario?"}
    )

    with pytest.raises(PlanningFailedError, match="only its displayed deterministic request"):
        asyncio.run(planner.plan(other_request))
