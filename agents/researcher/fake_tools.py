"""Deterministic search and source providers backed by shared fixtures."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agents.researcher.tools import (
    ResearchToolFailure,
    SearchProviderError,
    SearchQuery,
    SearchResult,
    SourceDocument,
    SourceProviderError,
)
from packages.testing import load_research_fixture


@dataclass(frozen=True)
class SearchCall:
    """An inspectable search invocation recorded by the fake provider."""

    query: SearchQuery


@dataclass(frozen=True)
class FetchCall:
    """An inspectable source fetch recorded by the fake provider."""

    result: SearchResult


class FakeSearchProvider:
    """Return deterministic search results or a configured typed failure."""

    def __init__(
        self,
        results: Sequence[SearchResult] = (),
        *,
        failure: ResearchToolFailure | None = None,
    ) -> None:
        self._results = tuple(result.model_copy(deep=True) for result in results)
        self._failure = failure.model_copy(deep=True) if failure else None
        self.calls: list[SearchCall] = []

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        validated_query = SearchQuery.model_validate(query.model_dump())
        self.calls.append(SearchCall(query=validated_query))
        if self._failure is not None:
            raise SearchProviderError(self._failure.model_copy(deep=True))
        return [result.model_copy(deep=True) for result in self._results[: query.limit]]


class FakeSourceProvider:
    """Return deterministic normalized documents keyed by search result ID."""

    def __init__(
        self,
        documents: Mapping[str, SourceDocument],
        *,
        failures: Mapping[str, ResearchToolFailure] | None = None,
    ) -> None:
        self._documents = {
            source_id: document.model_copy(deep=True) for source_id, document in documents.items()
        }
        self._failures = {
            source_id: failure.model_copy(deep=True)
            for source_id, failure in (failures or {}).items()
        }
        self.calls: list[FetchCall] = []

    async def fetch(self, result: SearchResult) -> SourceDocument:
        validated_result = SearchResult.model_validate(result.model_dump())
        self.calls.append(FetchCall(result=validated_result))
        if failure := self._failures.get(result.source_id):
            raise SourceProviderError(failure.model_copy(deep=True))
        try:
            document = self._documents[result.source_id]
        except KeyError as error:
            raise SourceProviderError(
                ResearchToolFailure(
                    code="fixture_source_not_found",
                    message=f"No deterministic source exists for {result.source_id}.",
                    provider="fixture",
                    operation="fetch",
                    retryable=False,
                    source_id=result.source_id,
                )
            ) from error
        return document.model_copy(deep=True)


def create_fixture_providers(
    fixture_id: str,
) -> tuple[FakeSearchProvider, FakeSourceProvider]:
    """Build fake tool providers from one shared research scenario."""
    fixture = load_research_fixture(fixture_id)
    if fixture.failure is not None:
        failure = ResearchToolFailure(
            code=fixture.failure.code,
            message=fixture.failure.message,
            provider="fixture",
            operation="search",
            retryable=fixture.failure.retryable,
        )
        return FakeSearchProvider(failure=failure), FakeSourceProvider({})

    if fixture.evidence_bundle is None:  # pragma: no cover - guarded by ResearchFixture
        raise ValueError(f"Fixture {fixture_id} has neither evidence nor a failure.")

    results = [
        SearchResult(
            source_id=evidence.id,
            title=evidence.title,
            snippet=evidence.summary,
            source_url=evidence.source_url,
            source_type=evidence.source_type,
        )
        for evidence in fixture.evidence_bundle.evidence
    ]
    documents = {
        evidence.id: SourceDocument(
            source_id=evidence.id,
            title=evidence.title,
            content=evidence.summary,
            source_url=evidence.source_url,
            source_type=evidence.source_type,
            retrieved_at=evidence.retrieved_at,
        )
        for evidence in fixture.evidence_bundle.evidence
    }
    return FakeSearchProvider(results), FakeSourceProvider(documents)
