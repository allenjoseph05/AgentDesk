"""Runnable deterministic Analyst Agent configuration for tests and local demos."""

from __future__ import annotations

import asyncio
import os

from pydantic import BaseModel

from agents.analyst.analysis import DecisionAnalyzer
from agents.analyst.executor import AnalystAgentExecutor
from agents.analyst.main import create_app
from packages.contracts import DecisionAnalysis, RecommendationChallenge
from packages.llm import FakeLLMProvider, Message
from packages.testing import load_research_fixture

DEFAULT_FIXTURE_ID = "postgresql-vs-mongodb-golden"


class DelayedFixtureLLMProvider:
    """Add a deterministic cancellation window around the fixture provider."""

    def __init__(self, provider: FakeLLMProvider, delay_seconds: float) -> None:
        if delay_seconds < 0:
            raise ValueError("Fixture analysis delay cannot be negative.")
        self._provider = provider
        self._delay_seconds = delay_seconds

    async def generate_structured[ResponseT: BaseModel](
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        response_model: type[ResponseT],
    ) -> ResponseT:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        return await self._provider.generate_structured(
            system_prompt=system_prompt,
            messages=messages,
            response_model=response_model,
        )


def create_fixture_executor(
    fixture_id: str = DEFAULT_FIXTURE_ID,
    *,
    analysis_delay_seconds: float = 0,
) -> AnalystAgentExecutor:
    """Compose the production Analyst boundary with deterministic typed outputs."""
    fixture = load_research_fixture(fixture_id)
    if fixture.evidence_bundle is None or fixture.decision_analysis is None:
        raise ValueError(f"Analyst fixture requires evidence and analysis: {fixture_id}")
    outputs: dict[type[BaseModel], BaseModel] = {
        DecisionAnalysis: fixture.decision_analysis,
    }
    if fixture.recommendation_challenge is not None:
        outputs[RecommendationChallenge] = fixture.recommendation_challenge
    provider = DelayedFixtureLLMProvider(
        FakeLLMProvider(outputs),
        analysis_delay_seconds,
    )
    return AnalystAgentExecutor(DecisionAnalyzer(provider))


_fixture_id = os.getenv("ANALYST_FIXTURE_ID", DEFAULT_FIXTURE_ID)
_analysis_delay = float(os.getenv("ANALYST_FIXTURE_DELAY_SECONDS", "0"))
app = create_app(
    executor=create_fixture_executor(_fixture_id, analysis_delay_seconds=_analysis_delay)
)
