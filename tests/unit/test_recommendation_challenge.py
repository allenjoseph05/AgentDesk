"""Evidence-grounding tests for recommendation challenge mode."""

import asyncio
import json

import pytest

from agents.analyst import (
    RECOMMENDATION_CHALLENGE_PROMPT,
    DecisionAnalyzer,
    RecommendationChallengeError,
)
from packages.contracts import AnalysisRequest, RecommendationChallenge
from packages.llm import FakeLLMProvider
from packages.testing import load_research_fixture


def _request_and_challenge() -> tuple[AnalysisRequest, RecommendationChallenge]:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    if (
        fixture.evidence_bundle is None
        or fixture.decision_analysis is None
        or fixture.recommendation_challenge is None
    ):
        raise AssertionError("Golden fixture must contain evidence, analysis, and challenge.")
    request = AnalysisRequest(
        question=fixture.request.question,
        options=fixture.request.options,
        constraints=fixture.request.constraints,
        criteria=fixture.request.criteria,
        evidence_bundle=fixture.evidence_bundle,
        mode="challenge_current_recommendation",
        current_recommendation=fixture.decision_analysis.recommendation,
    )
    return request, fixture.recommendation_challenge


def _challenge(
    request: AnalysisRequest,
    candidate: RecommendationChallenge,
) -> RecommendationChallenge:
    provider = FakeLLMProvider({RecommendationChallenge: candidate})
    return asyncio.run(DecisionAnalyzer(provider).challenge(request))


def test_challenge_returns_the_strongest_grounded_alternative_as_a_typed_output() -> None:
    request, candidate = _request_and_challenge()
    provider = FakeLLMProvider({RecommendationChallenge: candidate})

    challenge = asyncio.run(DecisionAnalyzer(provider).challenge(request))

    assert challenge.current_recommendation == "PostgreSQL"
    assert challenge.strongest_alternative == "MongoDB"
    assert challenge.strongest_counterargument
    assert set(challenge.supporting_claim_ids) <= {
        claim.id for claim in request.evidence_bundle.claims
    }
    assert challenge.assumptions
    assert challenge.recommendation_changes_if

    call = provider.calls[0]
    assert call.response_model is RecommendationChallenge
    assert "strongest credible case" in RECOMMENDATION_CHALLENGE_PROMPT
    assert "external or prior" in call.system_prompt
    assert json.loads(call.messages[0].content) == request.model_dump(mode="json")


def test_challenge_rejects_a_different_current_recommendation() -> None:
    request, candidate = _request_and_challenge()
    candidate.current_recommendation = "MongoDB"

    with pytest.raises(RecommendationChallengeError, match="preserve") as error:
        _challenge(request, candidate)

    assert error.value.code == "recommendation_mismatch"


@pytest.mark.parametrize("alternative", ["PostgreSQL", "Redis"])
def test_challenge_requires_a_different_supplied_alternative(alternative: str) -> None:
    request, candidate = _request_and_challenge()
    candidate.strongest_alternative = alternative

    with pytest.raises(RecommendationChallengeError, match="different alternative") as error:
        _challenge(request, candidate)

    assert error.value.code == "invalid_alternative"


def test_challenge_rejects_an_invented_claim_reference() -> None:
    request, candidate = _request_and_challenge()
    candidate.supporting_claim_ids = ["claim-from-outside-evidence"]

    with pytest.raises(RecommendationChallengeError, match="unknown claims") as error:
        _challenge(request, candidate)

    assert error.value.code == "unsupported_claim_reference"


def test_challenge_method_rejects_compare_options_mode() -> None:
    request, candidate = _request_and_challenge()
    compare_request = request.model_copy(
        update={"mode": "compare_options", "current_recommendation": None},
        deep=True,
    )

    with pytest.raises(RecommendationChallengeError, match="challenge_current") as error:
        _challenge(compare_request, candidate)

    assert error.value.code == "unsupported_mode"
