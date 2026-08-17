"""Typed plan generation, retry, and registry-binding tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel, ValidationError

from agents.analyst.agent_card import create_agent_card as create_analyst_card
from agents.coordinator.planner import (
    PLANNER_PROMPT,
    DecisionPlanner,
    PlanDraft,
    PlanningFailedError,
    WorkflowPlan,
)
from agents.coordinator.registry import (
    AgentEndpointConfig,
    AgentRegistry,
    AgentRegistrySettings,
)
from agents.researcher.agent_card import create_agent_card as create_research_card
from packages.contracts import ResearchRequest
from packages.llm import LLMResponseError, Message


class ScriptedProvider:
    """Return typed or malformed planner outputs in a deterministic sequence."""

    def __init__(self, responses: list[BaseModel | Mapping[str, Any] | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, tuple[Message, ...], type[BaseModel]]] = []

    async def generate_structured[ResponseT: BaseModel](
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        response_model: type[ResponseT],
    ) -> ResponseT:
        self.calls.append((system_prompt, tuple(messages), response_model))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        raw = response.model_dump(mode="python") if isinstance(response, BaseModel) else response
        try:
            return response_model.model_validate(raw)
        except ValidationError as error:
            raise LLMResponseError("Scripted planner output failed validation.") from error


def _request() -> ResearchRequest:
    return ResearchRequest(
        question="Should the product use PostgreSQL or MongoDB?",
        options=["PostgreSQL", "MongoDB"],
        constraints=["Preserve transactional integrity"],
        criteria=["Data integrity", "Schema flexibility"],
    )


def _draft() -> PlanDraft:
    return PlanDraft(
        goal="compare_options",
        criteria=["Data integrity", "Schema flexibility"],
        steps=[
            {
                "step_id": "research",
                "skill": "web-research",
                "scope": "Collect evidence for the named options and criteria.",
            },
            {
                "step_id": "analysis",
                "skill": "decision-analysis",
                "scope": "Score the options using the collected evidence.",
                "depends_on": ["research"],
            },
        ],
    )


def _registry(*, include_analyst: bool = True) -> AgentRegistry:
    endpoints = [
        AgentEndpointConfig(agent_id="researcher", base_url="https://research.example")
    ]
    cards: dict[str, dict[str, object]] = {
        "https://research.example/.well-known/agent-card.json": MessageToDict(
            create_research_card("https://research.example")
        )
    }
    if include_analyst:
        endpoints.append(
            AgentEndpointConfig(agent_id="analyst", base_url="https://analyst.example")
        )
        cards["https://analyst.example/.well-known/agent-card.json"] = MessageToDict(
            create_analyst_card("https://analyst.example")
        )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=cards[str(request.url)])

    registry = AgentRegistry(
        AgentRegistrySettings(endpoints=endpoints, request_timeout_seconds=1),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    asyncio.run(registry.refresh())
    return registry


def test_planner_returns_typed_steps_with_registry_derived_providers() -> None:
    registry = _registry()
    provider = ScriptedProvider([_draft()])

    plan = asyncio.run(
        DecisionPlanner(llm_provider=provider, registry=registry).plan(_request())
    )

    assert isinstance(plan, WorkflowPlan)
    assert plan.goal == "compare_options"
    assert plan.criteria == _request().criteria
    assert [step.skill for step in plan.steps] == ["web-research", "decision-analysis"]
    provider_assignments = [
        (step.provider_agent_id, str(step.provider_base_url).rstrip("/"))
        for step in plan.steps
    ]
    assert provider_assignments == [
        ("researcher", "https://research.example"),
        ("analyst", "https://analyst.example"),
    ]
    assert plan.steps[1].depends_on == [plan.steps[0].step_id]

    system_prompt, messages, response_model = provider.calls[0]
    assert system_prompt == PLANNER_PROMPT
    assert response_model is PlanDraft
    context = json.loads(messages[0].content)
    assert context["registered_capabilities"] == [
        {
            "agent_id": "researcher",
            "skills": ["web-research", "source-synthesis"],
        },
        {"agent_id": "analyst", "skills": ["decision-analysis"]},
    ]
    assert "https://" not in messages[0].content


def test_model_supplied_service_url_is_rejected_then_retried_without_using_it() -> None:
    malformed = _draft().model_dump(mode="python")
    malformed["steps"][0]["service_url"] = "https://invented.example"
    provider = ScriptedProvider([malformed, _draft()])

    plan = asyncio.run(
        DecisionPlanner(llm_provider=provider, registry=_registry(), max_attempts=2).plan(
            _request()
        )
    )

    assert len(provider.calls) == 2
    assert all("invented.example" not in str(step.provider_base_url) for step in plan.steps)
    assert json.loads(provider.calls[1][1][0].content)["validation_feedback"] == (
        "provider_output_invalid"
    )


def test_semantically_invalid_plan_is_retried_with_bounded_feedback() -> None:
    wrong_criteria = _draft().model_copy(
        update={"criteria": ["Cost only"]},
        deep=True,
    )
    provider = ScriptedProvider([wrong_criteria, _draft()])

    plan = asyncio.run(
        DecisionPlanner(llm_provider=provider, registry=_registry(), max_attempts=2).plan(
            _request()
        )
    )

    assert plan.criteria == _request().criteria
    assert len(provider.calls) == 2
    retry_context = json.loads(provider.calls[1][1][0].content)
    assert retry_context["validation_feedback"] == "criteria_mismatch"


def test_missing_registered_skill_exhausts_exact_attempt_budget() -> None:
    provider = ScriptedProvider([_draft(), _draft(), _draft()])

    with pytest.raises(PlanningFailedError, match="skill_unavailable") as error:
        asyncio.run(
            DecisionPlanner(
                llm_provider=provider,
                registry=_registry(include_analyst=False),
                max_attempts=2,
            ).plan(_request())
        )

    assert error.value.code == "attempts_exhausted"
    assert error.value.attempts == 2
    assert len(provider.calls) == 2


def test_request_with_fewer_than_two_options_fails_before_model_call() -> None:
    provider = ScriptedProvider([_draft()])
    request = ResearchRequest(
        question="Should we keep PostgreSQL?",
        options=["PostgreSQL"],
        criteria=["Data integrity"],
    )

    with pytest.raises(PlanningFailedError, match="at least two") as error:
        asyncio.run(DecisionPlanner(llm_provider=provider, registry=_registry()).plan(request))

    assert error.value.code == "insufficient_options"
    assert error.value.attempts == 0
    assert provider.calls == []


def test_plan_draft_rejects_unknown_fields_and_dependency_cycles() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PlanDraft.model_validate({**_draft().model_dump(), "service_url": "https://bad.example"})

    cyclic = _draft().model_dump(mode="python")
    cyclic["steps"][0]["depends_on"] = ["analysis"]
    with pytest.raises(ValidationError, match="cycle"):
        PlanDraft.model_validate(cyclic)
