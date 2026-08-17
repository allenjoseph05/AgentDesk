"""Runnable deterministic Research Agent configuration for tests and local demos."""

from __future__ import annotations

import asyncio
import os

from agents.researcher.executor import ResearchAgentExecutor
from agents.researcher.fake_tools import FakeSearchProvider, create_fixture_providers
from agents.researcher.main import create_app
from agents.researcher.synthesis import ResearchSynthesizer
from agents.researcher.tools import SearchQuery, SearchResult
from packages.contracts import EvidenceBundle
from packages.llm import FakeLLMProvider
from packages.testing import load_research_fixture

DEFAULT_FIXTURE_ID = "postgresql-vs-mongodb-golden"


class DelayedSearchProvider:
    """Add a deterministic cancellation window around a fake search provider."""

    def __init__(self, provider: FakeSearchProvider, delay_seconds: float) -> None:
        if delay_seconds < 0:
            raise ValueError("Fixture search delay cannot be negative.")
        self._provider = provider
        self._delay_seconds = delay_seconds

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        return await self._provider.search(query)


def create_fixture_executor(
    fixture_id: str = DEFAULT_FIXTURE_ID,
    *,
    search_delay_seconds: float = 0,
) -> ResearchAgentExecutor:
    """Compose the production executor boundary with deterministic providers."""
    fixture = load_research_fixture(fixture_id)
    search_provider, source_provider = create_fixture_providers(fixture_id)
    llm_fixtures = (
        {EvidenceBundle: fixture.evidence_bundle} if fixture.evidence_bundle is not None else {}
    )
    synthesizer = ResearchSynthesizer(
        search_provider=DelayedSearchProvider(search_provider, search_delay_seconds),
        source_provider=source_provider,
        llm_provider=FakeLLMProvider(llm_fixtures),
    )
    return ResearchAgentExecutor(synthesizer)


_fixture_id = os.getenv("RESEARCH_FIXTURE_ID", DEFAULT_FIXTURE_ID)
_search_delay = float(os.getenv("RESEARCH_FIXTURE_SEARCH_DELAY_SECONDS", "0"))
app = create_app(executor=create_fixture_executor(_fixture_id, search_delay_seconds=_search_delay))
