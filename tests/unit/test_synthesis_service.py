"""Authoritative-artifact tests for final Coordinator synthesis."""

from datetime import UTC, datetime

import pytest

from agents.coordinator.synthesis import SynthesisError, SynthesisService
from packages.contracts import (
    ArtifactEnvelope,
    ArtifactProvenance,
    DecisionAnalysis,
    EvidenceBundle,
    FinalSynthesis,
)
from packages.testing import load_research_fixture


def _artifacts(
    fixture_id: str = "postgresql-vs-mongodb-golden",
) -> tuple[str, ArtifactEnvelope[EvidenceBundle], ArtifactEnvelope[DecisionAnalysis]]:
    fixture = load_research_fixture(fixture_id)
    if fixture.evidence_bundle is None or fixture.decision_analysis is None:
        raise AssertionError("Synthesis fixture requires evidence and analysis.")
    created_at = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    return (
        fixture.request.question,
        ArtifactEnvelope[EvidenceBundle](
            provenance=ArtifactProvenance(
                producer_agent="researcher",
                remote_task_id="research-task-1",
                created_at=created_at,
            ),
            payload=fixture.evidence_bundle,
        ),
        ArtifactEnvelope[DecisionAnalysis](
            provenance=ArtifactProvenance(
                producer_agent="analyst",
                remote_task_id="analysis-task-1",
                created_at=created_at,
            ),
            payload=fixture.decision_analysis,
        ),
    )


def test_synthesis_preserves_authoritative_analysis_and_provenance() -> None:
    question, evidence, analysis = _artifacts()

    result = SynthesisService().synthesize(
        question=question,
        evidence_artifact=evidence,
        analysis_artifact=analysis,
    )

    assert isinstance(result, FinalSynthesis)
    assert result.summary == analysis.payload.executive_summary
    assert result.recommendation == analysis.payload.recommendation
    assert result.assumptions == analysis.payload.assumptions
    assert result.supporting_claim_ids == ["claim-pg", "claim-mongo"]
    assert result.evidence_count == len(evidence.payload.evidence)
    assert result.research_task_id == "research-task-1"
    assert result.analysis_task_id == "analysis-task-1"
    assert result.warnings == [
        "Evidence gap: Production access patterns are not measured.",
        "Research note: Deterministic fixture; not a live benchmark.",
        "Decision risk: Unmeasured workloads could change the tradeoff.",
    ]


def test_partial_evidence_gaps_and_analysis_risks_are_visible_warnings() -> None:
    question, evidence, analysis = _artifacts("postgresql-vs-mongodb-partial")

    result = SynthesisService().synthesize(
        question=question,
        evidence_artifact=evidence,
        analysis_artifact=analysis,
    )

    warning_text = " ".join(result.warnings)
    assert "MongoDB evidence is unavailable" in warning_text
    assert "Operational cost was not evaluated" in warning_text
    assert "recommendation may change" in warning_text
    assert result.recommendation == "PostgreSQL"
    assert "provisional" in result.summary.casefold()


@pytest.mark.parametrize(
    ("missing", "expected_code"),
    [("evidence", "missing_evidence"), ("analysis", "missing_analysis")],
)
def test_missing_specialist_artifact_is_never_silently_replaced(
    missing: str,
    expected_code: str,
) -> None:
    question, evidence, analysis = _artifacts()

    with pytest.raises(SynthesisError) as error:
        SynthesisService().synthesize(
            question=question,
            evidence_artifact=None if missing == "evidence" else evidence,
            analysis_artifact=None if missing == "analysis" else analysis,
        )

    assert error.value.code == expected_code


def test_analysis_cannot_reference_a_claim_missing_from_research() -> None:
    question, evidence, analysis = _artifacts()
    altered = analysis.model_copy(deep=True)
    altered.payload.criteria[0].supporting_claim_ids = ["invented-claim"]

    with pytest.raises(SynthesisError, match="absent from Research") as error:
        SynthesisService().synthesize(
            question=question,
            evidence_artifact=evidence,
            analysis_artifact=altered,
        )

    assert error.value.code == "unsupported_analysis"


def test_evidence_for_a_different_question_is_rejected() -> None:
    _, evidence, analysis = _artifacts()

    with pytest.raises(SynthesisError, match="does not belong") as error:
        SynthesisService().synthesize(
            question="Should the product use Redis?",
            evidence_artifact=evidence,
            analysis_artifact=analysis,
        )

    assert error.value.code == "question_mismatch"
