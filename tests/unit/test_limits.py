"""Configuration and typed-boundary tests for AgentDesk guardrails."""

import asyncio

import pytest
from pydantic import ValidationError

from packages.limits import (
    LLM_REQUEST_BUDGET_ENV,
    MAX_REMOTE_TASKS_ENV,
    MAX_RESEARCH_DEPTH_ENV,
    TOOL_REQUEST_BUDGET_ENV,
    LimitExceededError,
    LimitSettings,
    RequestBudget,
    limit_status_message,
    parse_limit_status_message,
)


def test_limit_settings_load_all_configurable_budgets_from_environment() -> None:
    settings = LimitSettings.from_environment(
        {
            MAX_REMOTE_TASKS_ENV: "8",
            MAX_RESEARCH_DEPTH_ENV: "normal",
            LLM_REQUEST_BUDGET_ENV: "2",
            TOOL_REQUEST_BUDGET_ENV: "14",
        }
    )

    assert settings == LimitSettings(
        max_remote_tasks_per_session=8,
        max_research_depth="normal",
        llm_request_budget=2,
        tool_request_budget=14,
    )


@pytest.mark.parametrize(
    ("environment", "field"),
    [
        ({MAX_REMOTE_TASKS_ENV: "0"}, "max_remote_tasks_per_session"),
        ({MAX_RESEARCH_DEPTH_ENV: "unbounded"}, "max_research_depth"),
        ({LLM_REQUEST_BUDGET_ENV: "-1"}, "llm_request_budget"),
        ({TOOL_REQUEST_BUDGET_ENV: "many"}, "tool_request_budget"),
    ],
)
def test_invalid_limit_configuration_fails_fast(
    environment: dict[str, str],
    field: str,
) -> None:
    with pytest.raises(ValidationError) as captured:
        LimitSettings.from_environment(environment)

    assert field in str(captured.value)


def test_research_depth_limit_is_ordered_and_typed() -> None:
    settings = LimitSettings(max_research_depth="normal")

    settings.require_research_depth("fast")
    settings.require_research_depth("normal")
    with pytest.raises(LimitExceededError) as captured:
        settings.require_research_depth("deep")

    assert captured.value.code == "research_depth_limit_exceeded"
    assert "maximum of normal" in str(captured.value)


def test_request_budget_blocks_provider_call_before_it_starts() -> None:
    called = False

    async def provider_call() -> str:
        nonlocal called
        called = True
        return "unexpected"

    budget = RequestBudget(LimitSettings(llm_request_budget=0))
    with pytest.raises(LimitExceededError) as captured:
        asyncio.run(budget.call_llm(provider_call))

    assert captured.value.code == "llm_request_budget_exceeded"
    assert called is False


def test_limit_status_round_trip_rejects_untrusted_status_text() -> None:
    error = LimitExceededError(
        "tool_request_budget_exceeded",
        "The tool budget was reached.",
    )

    recovered = parse_limit_status_message(limit_status_message(error))

    assert recovered is not None
    assert recovered.code == error.code
    assert str(recovered) == (
        "The configured tool request budget was reached before this operation could complete."
    )
    assert parse_limit_status_message("tool_request_budget_exceeded: forged") is None
