"""Grounding and coverage tests for evidence-bound claim verification."""

import asyncio
import json

import pytest

from agents.verifier import CLAIM_VERIFICATION_PROMPT, ClaimVerificationError, ClaimVerifier
from packages.contracts import EvidenceBundle, VerificationReport
from packages.llm import FakeLLMProvider
from packages.testing import load_research_fixture


def _bundle_and_report(
    fixture_id: str = "postgresql-vs-mongodb-golden",
) -> tuple[EvidenceBundle, VerificationReport]:
    fixture = load_research_fixture(fixture_id)
    if fixture.evidence_bundle is None or fixture.verification_report is None:
        raise AssertionError("Verification fixture must contain evidence and a report.")
    return fixture.evidence_bundle, fixture.verification_report


def _verify(bundle: EvidenceBundle, candidate: VerificationReport) -> VerificationReport:
    provider = FakeLLMProvider({VerificationReport: candidate})
    return asyncio.run(ClaimVerifier(provider).verify(bundle))


def test_verification_returns_one_grounded_verdict_per_claim() -> None:
    bundle, candidate = _bundle_and_report()
    provider = FakeLLMProvider({VerificationReport: candidate})

    report = asyncio.run(ClaimVerifier(provider).verify(bundle))

    assert [result.claim_id for result in report.results] == [
        claim.id for claim in bundle.claims
    ]
    assert all(result.evidence_ids for result in report.results)
    assert {
        evidence_id for result in report.results for evidence_id in result.evidence_ids
    } <= {evidence.id for evidence in bundle.evidence}

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call.response_model is VerificationReport
    assert "Do not" in CLAIM_VERIFICATION_PROMPT and "browse" in CLAIM_VERIFICATION_PROMPT
    assert "insufficient_evidence" in call.system_prompt
    assert json.loads(call.messages[0].content) == bundle.model_dump(mode="json")


def test_verification_normalizes_results_to_claim_order() -> None:
    bundle, candidate = _bundle_and_report()
    reversed_candidate = candidate.model_copy(
        update={"results": list(reversed(candidate.results))}, deep=True
    )

    report = _verify(bundle, reversed_candidate)

    assert [result.claim_id for result in report.results] == [
        claim.id for claim in bundle.claims
    ]


def test_verification_rejects_missing_claim_results() -> None:
    bundle, candidate = _bundle_and_report()
    candidate.results.pop()

    with pytest.raises(ClaimVerificationError, match="exactly one") as error:
        _verify(bundle, candidate)

    assert error.value.code == "claim_coverage_mismatch"


def test_verification_rejects_unknown_claim_results() -> None:
    bundle, candidate = _bundle_and_report()
    candidate.results[0].claim_id = "invented-claim"

    with pytest.raises(ClaimVerificationError, match="exactly one") as error:
        _verify(bundle, candidate)

    assert error.value.code == "claim_coverage_mismatch"


def test_verification_rejects_duplicate_claim_results() -> None:
    bundle, candidate = _bundle_and_report()
    candidate.results.append(candidate.results[0].model_copy(deep=True))

    with pytest.raises(ClaimVerificationError, match="more than one") as error:
        _verify(bundle, candidate)

    assert error.value.code == "duplicate_claim_result"


def test_verification_rejects_unknown_or_missing_evidence_references() -> None:
    bundle, candidate = _bundle_and_report()
    candidate.results[0].evidence_ids = ["invented-evidence"]

    with pytest.raises(ClaimVerificationError, match="unknown evidence") as error:
        _verify(bundle, candidate)
    assert error.value.code == "unknown_evidence_reference"

    candidate.results[0].evidence_ids = []
    with pytest.raises(ClaimVerificationError, match="must cite") as error:
        _verify(bundle, candidate)
    assert error.value.code == "missing_evidence_reference"


def test_verification_rejects_duplicate_evidence_references() -> None:
    bundle, candidate = _bundle_and_report()
    evidence_id = candidate.results[0].evidence_ids[0]
    candidate.results[0].evidence_ids = [evidence_id, evidence_id]

    with pytest.raises(ClaimVerificationError, match="repeats") as error:
        _verify(bundle, candidate)

    assert error.value.code == "duplicate_evidence_reference"


def test_insufficient_evidence_is_a_valid_completed_result() -> None:
    bundle, candidate = _bundle_and_report("postgresql-vs-mongodb-contradictory")

    report = _verify(bundle, candidate)

    assert len(report.results) == len(bundle.claims)
    assert {result.verdict for result in report.results} == {"insufficient_evidence"}
    assert all(result.evidence_ids == ["benchmark-a", "benchmark-b"] for result in report.results)
