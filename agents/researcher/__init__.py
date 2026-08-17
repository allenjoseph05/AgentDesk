"""Independently deployable AgentDesk Research Agent."""

from agents.researcher.fake_tools import (
    FakeSearchProvider,
    FakeSourceProvider,
    create_fixture_providers,
)
from agents.researcher.tools import (
    ResearchToolError,
    ResearchToolFailure,
    SearchProvider,
    SearchProviderError,
    SearchQuery,
    SearchResult,
    SourceDocument,
    SourceProvider,
    SourceProviderError,
)

__all__ = [
    "FakeSearchProvider",
    "FakeSourceProvider",
    "ResearchToolError",
    "ResearchToolFailure",
    "SearchProvider",
    "SearchProviderError",
    "SearchQuery",
    "SearchResult",
    "SourceDocument",
    "SourceProvider",
    "SourceProviderError",
    "create_fixture_providers",
]
