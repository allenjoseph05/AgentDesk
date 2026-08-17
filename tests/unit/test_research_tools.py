"""Tests for the Research Agent's provider-neutral tool boundary."""

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agents.researcher import (
    FakeSearchProvider,
    FakeSourceProvider,
    ResearchToolFailure,
    SearchProvider,
    SearchProviderError,
    SearchQuery,
    SearchResult,
    SourceDocument,
    SourceProvider,
    SourceProviderError,
    create_fixture_providers,
)


def test_fixture_providers_return_deterministic_search_and_source_data() -> None:
    search_provider, source_provider = create_fixture_providers("postgresql-vs-mongodb-golden")
    query = SearchQuery(text="PostgreSQL versus MongoDB", limit=1)

    first_results = asyncio.run(search_provider.search(query))
    second_results = asyncio.run(search_provider.search(query))
    document = asyncio.run(source_provider.fetch(first_results[0]))

    assert first_results == second_results
    assert first_results is not second_results
    assert [result.source_id for result in first_results] == ["evidence-pg"]
    assert document.source_id == "evidence-pg"
    assert "transactions" in document.content
    assert [call.query for call in search_provider.calls] == [query, query]
    assert source_provider.calls[0].result == first_results[0]
    assert isinstance(search_provider, SearchProvider)
    assert isinstance(source_provider, SourceProvider)


def test_failure_fixture_raises_typed_search_error() -> None:
    search_provider, _ = create_fixture_providers("postgresql-vs-mongodb-failure")

    with pytest.raises(SearchProviderError) as captured:
        asyncio.run(search_provider.search(SearchQuery(text="database comparison")))

    assert captured.value.failure == ResearchToolFailure(
        code="fixture_source_unavailable",
        message="The deterministic research source is unavailable.",
        provider="fixture",
        operation="search",
        retryable=True,
    )


def test_source_failure_preserves_retry_and_source_metadata() -> None:
    result = SearchResult(
        source_id="source-1",
        title="Unavailable source",
        snippet="A result whose body cannot currently be fetched.",
        source_type="primary_source",
    )
    failure = ResearchToolFailure(
        code="source_timeout",
        message="The source timed out.",
        provider="fake-external",
        operation="fetch",
        retryable=True,
        source_id=result.source_id,
    )
    provider = FakeSourceProvider({}, failures={result.source_id: failure})

    with pytest.raises(SourceProviderError) as captured:
        asyncio.run(provider.fetch(result))

    assert captured.value.failure == failure
    assert captured.value.failure.retryable is True
    assert captured.value.failure.source_id == "source-1"


def test_missing_fake_source_is_a_non_retryable_typed_error() -> None:
    result = SearchResult(
        source_id="missing",
        title="Missing source",
        snippet="This source is intentionally absent.",
        source_type="fixture",
    )

    with pytest.raises(SourceProviderError) as captured:
        asyncio.run(FakeSourceProvider({}).fetch(result))

    assert captured.value.failure.code == "fixture_source_not_found"
    assert captured.value.failure.operation == "fetch"
    assert captured.value.failure.retryable is False


def test_tool_models_reject_malformed_inputs() -> None:
    with pytest.raises(ValidationError):
        SearchQuery(text=" ", limit=0)
    with pytest.raises(ValidationError):
        SourceDocument(
            source_id="source-1",
            title="Source",
            content=" ",
            source_type="fixture",
            retrieved_at=datetime(2026, 8, 17, tzinfo=UTC),
        )


def test_fake_search_results_are_isolated_from_test_mutation() -> None:
    configured = SearchResult(
        source_id="source-1",
        title="Original title",
        snippet="Original snippet",
        source_type="fixture",
    )
    provider = FakeSearchProvider([configured])

    returned = asyncio.run(provider.search(SearchQuery(text="query")))
    returned[0].title = "Mutated title"

    fresh = asyncio.run(provider.search(SearchQuery(text="query")))
    assert fresh[0].title == "Original title"
