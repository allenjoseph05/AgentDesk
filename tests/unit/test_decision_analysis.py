"""Grounding and prompt tests for evidence-bound decision analysis."""

import asyncio
import json

import pytest

from agents.analyst import DECISION_ANALYSIS_PROMPT, DecisionAnalysisError, DecisionAnalyzer
from packages.contracts import AnalysisRequest, DecisionAnalysis
from packages.llm import FakeLLMProvider
from packages.testing import load_research_fixture


def _request_and_analysis() -> tuple[AnalysisRequest, DecisionAnalysis]:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    if fixture.evidence_bundle is None or fixture.decision_analysis is None:
        raise AssertionError("Golden fixture must contain evidence and analysis.")
    request = AnalysisRequest(
        question=fixture.request.question,
        options=fixture.request.options,
        constraints=fixture.request.constraints,
        criteria=fixture.request.criteria,
        evidence_bundle=fixture.evidence_bundle,
    )
    return request, fixture.decision_analysis


def _analyze(request: AnalysisRequest, candidate: DecisionAnalysis) -> DecisionAnalysis:
    return asyncio.run(
        DecisionAnalyzer(FakeLLMProvider({DecisionAnalysis: candidate})).analyze(request)
    )


def test_analysis_returns_complete_weighted_scores_grounded_in_supplied_claims() -> None:
    request, candidate = _request_and_analysis()
    provider = FakeLLMProvider({DecisionAnalysis: candidate})

    analysis = asyncio.run(DecisionAnalyzer(provider).analyze(request))

    assert analysis.recommendation == "PostgreSQL"
    assert [item.criterion for item in analysis.criteria] == request.criteria
    assert sum(item.weight for item in analysis.criteria) == pytest.approx(1)
    assert all(set(item.scores) == set(request.options) for item in analysis.criteria)
    assert {
        claim_id for item in analysis.criteria for claim_id in item.supporting_claim_ids
    } <= {claim.id for claim in request.evidence_bundle.claims}
    assert analysis.arguments_against
    assert analysis.assumptions
    assert analysis.risks
    assert analysis.recommendation_changes_if

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call.response_model is DecisionAnalysis
    assert "Do not browse" in DECISION_ANALYSIS_PROMPT
    assert "external or prior factual knowledge" in call.system_prompt
    assert json.loads(call.messages[0].content) == request.model_dump(mode="json")


def test_analysis_normalizes_criteria_to_the_requested_order() -> None:
    request, candidate = _request_and_analysis()
    reversed_candidate = candidate.model_copy(
        update={"criteria": list(reversed(candidate.criteria))}, deep=True
    )

    analysis = _analyze(request, reversed_candidate)

    assert [item.criterion for item in analysis.criteria] == request.criteria


def test_analysis_rejects_an_option_that_was_not_supplied() -> None:
    request, candidate = _request_and_analysis()
    candidate.recommendation = "Redis"

    with pytest.raises(DecisionAnalysisError, match="supplied options") as error:
        _analyze(request, candidate)

    assert error.value.code == "unknown_recommendation"


def test_analysis_rejects_incomplete_option_scores() -> None:
    request, candidate = _request_and_analysis()
    candidate.criteria[0].scores.pop("MongoDB")

    with pytest.raises(DecisionAnalysisError, match="cover exactly") as error:
        _analyze(request, candidate)

    assert error.value.code == "score_options_mismatch"


def test_analysis_rejects_weights_that_do_not_sum_to_one() -> None:
    request, candidate = _request_and_analysis()
    candidate.criteria[0].weight = 0.5

    with pytest.raises(DecisionAnalysisError, match="sum to 1") as error:
        _analyze(request, candidate)

    assert error.value.code == "invalid_weights"


def test_analysis_rejects_a_claim_id_not_present_in_supplied_evidence() -> None:
    request, candidate = _request_and_analysis()
    candidate.criteria[0].supporting_claim_ids = ["invented-claim"]

    with pytest.raises(DecisionAnalysisError, match="unknown claims") as error:
        _analyze(request, candidate)

    assert error.value.code == "unsupported_claim_reference"


def test_analysis_rejects_output_with_no_evidence_references() -> None:
    request, candidate = _request_and_analysis()
    for criterion in candidate.criteria:
        criterion.supporting_claim_ids = []

    with pytest.raises(DecisionAnalysisError, match="ground at least one") as error:
        _analyze(request, candidate)

    assert error.value.code == "ungrounded_analysis"
