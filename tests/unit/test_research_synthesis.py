"""Evidence extraction and synthesis tests for the Research Agent."""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from agents.researcher import (
    FakeSearchProvider,
    FakeSourceProvider,
    ResearchSynthesisError,
    ResearchSynthesizer,
    ResearchToolFailure,
    SearchProviderError,
    SearchQuery,
    SearchResult,
    SourceDocument,
    SourceProviderError,
    create_fixture_providers,
)
from packages.contracts import Claim, Evidence, EvidenceBundle, ResearchRequest
from packages.limits import LimitExceededError, LimitSettings
from packages.llm import FakeLLMProvider
from packages.testing import load_research_fixture


class FlakySearchProvider:
    """Fail once with a typed transient error, then return no results."""

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, _: SearchQuery) -> list[SearchResult]:
        self.calls += 1
        if self.calls == 1:
            raise SearchProviderError(
                ResearchToolFailure(
                    code="temporarily_unavailable",
                    message="Search is temporarily unavailable.",
                    provider="fixture",
                    operation="search",
                    retryable=True,
                )
            )
        return []


@pytest.mark.parametrize(
    ("fixture_id", "expected_limit"),
    [
        ("postgresql-vs-mongodb-golden", 5),
        ("postgresql-vs-mongodb-partial", 3),
        ("postgresql-vs-mongodb-contradictory", 10),
    ],
)
def test_fixture_research_produces_grounded_evidence_bundle_without_recommendation(
    fixture_id: str,
    expected_limit: int,
) -> None:
    fixture = load_research_fixture(fixture_id)
    if fixture.evidence_bundle is None:
        raise AssertionError("Successful synthesis fixture requires evidence.")
    search_provider, source_provider = create_fixture_providers(fixture_id)
    llm_provider = FakeLLMProvider({EvidenceBundle: fixture.evidence_bundle})
    synthesizer = ResearchSynthesizer(
        search_provider=search_provider,
        source_provider=source_provider,
        llm_provider=llm_provider,
    )

    bundle = asyncio.run(synthesizer.synthesize(fixture.request))

    assert bundle == fixture.evidence_bundle
    evidence_ids = {evidence.id for evidence in bundle.evidence}
    assert all(set(claim.evidence_ids) <= evidence_ids for claim in bundle.claims)
    assert search_provider.calls[0].query.limit == expected_limit
    assert fixture.request.question in search_provider.calls[0].query.text
    assert "recommendation" not in json.dumps(bundle.model_dump(mode="json")).casefold()
    assert llm_provider.calls[0].response_model is EvidenceBundle
    assert "do not choose a winner" in llm_provider.calls[0].system_prompt.casefold()
    context = json.loads(llm_provider.calls[0].messages[0].content)
    assert {source["source_id"] for source in context["sources"]} == evidence_ids


def test_fetch_failure_becomes_an_unknown_and_source_metadata_is_canonical() -> None:
    retrieved_at = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    good_result = SearchResult(
        source_id="source-good",
        title="Canonical source",
        snippet="Useful source",
        source_url="https://primary.example/source",
        source_type="primary_source",
    )
    failed_result = SearchResult(
        source_id="source-failed",
        title="Unavailable source",
        snippet="Could not be fetched",
        source_type="secondary_source",
    )
    source_failure = ResearchToolFailure(
        code="source_timeout",
        message="The source timed out.",
        provider="fixture",
        operation="fetch",
        retryable=True,
        source_id=failed_result.source_id,
    )
    search_provider = FakeSearchProvider([good_result, failed_result])
    source_provider = FakeSourceProvider(
        {
            good_result.source_id: SourceDocument(
                source_id=good_result.source_id,
                title=good_result.title,
                content="The primary source supports the scoped claim.",
                source_url=good_result.source_url,
                source_type=good_result.source_type,
                retrieved_at=retrieved_at,
            )
        },
        failures={failed_result.source_id: source_failure},
    )
    candidate = EvidenceBundle(
        question="What does the available source establish?",
        claims=[
            Claim(
                id="claim-1",
                statement="The available primary source supports the scoped claim.",
                evidence_ids=[good_result.source_id],
                confidence=0.8,
                caveats=["One search result could not be retrieved."],
            )
        ],
        evidence=[
            Evidence(
                id=good_result.source_id,
                title="Model-supplied title must not win",
                source_url="https://untrusted.example/invented",
                source_type="secondary_source",
                summary="The source supports the scoped claim.",
                relevance=0.8,
                retrieved_at=datetime(2025, 1, 1, tzinfo=UTC),
            )
        ],
        unknowns=[],
    )
    synthesizer = ResearchSynthesizer(
        search_provider=search_provider,
        source_provider=source_provider,
        llm_provider=FakeLLMProvider({EvidenceBundle: candidate}),
    )

    bundle = asyncio.run(
        synthesizer.synthesize(ResearchRequest(question=candidate.question, desired_depth="fast"))
    )

    evidence = bundle.evidence[0]
    assert evidence.title == "Canonical source"
    assert str(evidence.source_url) == "https://primary.example/source"
    assert evidence.source_type == "primary_source"
    assert evidence.retrieved_at == retrieved_at
    assert any("source-failed" in unknown and "timed out" in unknown for unknown in bundle.unknowns)
    assert any("source_timeout" in note for note in bundle.research_notes)


def test_all_source_failures_preserve_the_typed_provider_error() -> None:
    result = SearchResult(
        source_id="source-failed",
        title="Unavailable",
        snippet="Unavailable source",
        source_type="fixture",
    )
    failure = ResearchToolFailure(
        code="source_unavailable",
        message="No source body was available.",
        provider="fixture",
        operation="fetch",
        retryable=True,
        source_id=result.source_id,
    )
    synthesizer = ResearchSynthesizer(
        search_provider=FakeSearchProvider([result]),
        source_provider=FakeSourceProvider({}, failures={result.source_id: failure}),
        llm_provider=FakeLLMProvider({}),
    )

    with pytest.raises(SourceProviderError) as captured:
        asyncio.run(synthesizer.synthesize(ResearchRequest(question="What is known?")))

    assert captured.value.failure == failure


def test_synthesis_rejects_evidence_not_returned_by_the_source_provider() -> None:
    retrieved_at = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    result = SearchResult(
        source_id="source-real",
        title="Real source",
        snippet="Real source snippet",
        source_type="fixture",
    )
    source_provider = FakeSourceProvider(
        {
            result.source_id: SourceDocument(
                source_id=result.source_id,
                title=result.title,
                content="Grounded content.",
                source_type="fixture",
                retrieved_at=retrieved_at,
            )
        }
    )
    ungrounded = EvidenceBundle(
        question="What is known?",
        claims=[
            Claim(
                id="claim-invented",
                statement="An invented source supports this claim.",
                evidence_ids=["source-invented"],
            )
        ],
        evidence=[
            Evidence(
                id="source-invented",
                title="Invented",
                source_type="fixture",
                summary="Invented material.",
                relevance=0.5,
                retrieved_at=retrieved_at,
            )
        ],
        unknowns=[],
    )
    synthesizer = ResearchSynthesizer(
        search_provider=FakeSearchProvider([result]),
        source_provider=source_provider,
        llm_provider=FakeLLMProvider({EvidenceBundle: ungrounded}),
    )

    with pytest.raises(ResearchSynthesisError) as captured:
        asyncio.run(synthesizer.synthesize(ResearchRequest(question="What is known?")))

    assert captured.value.code == "ungrounded_evidence"


def test_empty_search_result_is_a_typed_synthesis_failure() -> None:
    synthesizer = ResearchSynthesizer(
        search_provider=FakeSearchProvider([]),
        source_provider=FakeSourceProvider({}),
        llm_provider=FakeLLMProvider({}),
    )

    with pytest.raises(ResearchSynthesisError) as captured:
        asyncio.run(synthesizer.synthesize(ResearchRequest(question="What is known?")))

    assert captured.value.code == "no_search_results"


def test_retryable_search_failure_is_replayed_only_within_the_safe_budget() -> None:
    search_provider = FlakySearchProvider()
    synthesizer = ResearchSynthesizer(
        search_provider=search_provider,
        source_provider=FakeSourceProvider({}),
        llm_provider=FakeLLMProvider({}),
        tool_max_attempts=2,
        retry_delay_seconds=0,
    )

    with pytest.raises(ResearchSynthesisError) as captured:
        asyncio.run(synthesizer.synthesize(ResearchRequest(question="What is known?")))

    assert captured.value.code == "no_search_results"
    assert search_provider.calls == 2


def test_tool_budget_counts_actual_search_and_fetch_attempts() -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    search_provider, source_provider = create_fixture_providers("postgresql-vs-mongodb-golden")
    synthesizer = ResearchSynthesizer(
        search_provider=search_provider,
        source_provider=source_provider,
        llm_provider=FakeLLMProvider({}),
        limit_settings=LimitSettings(tool_request_budget=1),
    )

    with pytest.raises(LimitExceededError) as captured:
        asyncio.run(synthesizer.synthesize(fixture.request))

    assert captured.value.code == "tool_request_budget_exceeded"
    assert len(search_provider.calls) == 1
    assert source_provider.calls == []


def test_empty_model_synthesis_is_rejected_even_when_sources_exist() -> None:
    retrieved_at = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    result = SearchResult(
        source_id="source-1",
        title="Available source",
        snippet="Available",
        source_type="fixture",
    )
    candidate = EvidenceBundle(
        question="What is known?",
        claims=[],
        evidence=[],
        unknowns=["The model did not extract a claim."],
    )
    synthesizer = ResearchSynthesizer(
        search_provider=FakeSearchProvider([result]),
        source_provider=FakeSourceProvider(
            {
                result.source_id: SourceDocument(
                    source_id=result.source_id,
                    title=result.title,
                    content="Source content.",
                    source_type="fixture",
                    retrieved_at=retrieved_at,
                )
            }
        ),
        llm_provider=FakeLLMProvider({EvidenceBundle: candidate}),
    )

    with pytest.raises(ResearchSynthesisError) as captured:
        asyncio.run(synthesizer.synthesize(ResearchRequest(question="What is known?")))

    assert captured.value.code == "empty_synthesis"
