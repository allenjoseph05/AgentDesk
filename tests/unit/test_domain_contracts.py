"""Validation coverage for shared cross-agent domain contracts."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from packages.contracts import (
    ArtifactEnvelope,
    ArtifactProvenance,
    Claim,
    CriterionScore,
    DecisionAnalysis,
    Evidence,
    EvidenceBundle,
    ResearchRequest,
    VerificationReport,
    VerificationResult,
)


def valid_evidence() -> Evidence:
    return Evidence(
        id="evidence-1",
        title="PostgreSQL documentation",
        source_url="https://www.postgresql.org/docs/current/",
        source_type="official_documentation",
        summary="PostgreSQL supports relational constraints and JSON data.",
        relevance=0.95,
        retrieved_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    )


def valid_claim() -> Claim:
    return Claim(
        id="claim-1",
        statement="PostgreSQL supports relational integrity constraints.",
        evidence_ids=["evidence-1"],
        confidence=0.9,
    )


def valid_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        question="Should this workload use PostgreSQL or MongoDB?",
        claims=[valid_claim()],
        evidence=[valid_evidence()],
        unknowns=["Production query distribution is not yet measured."],
        research_notes=["Compared primary documentation first."],
    )


def valid_provenance() -> ArtifactProvenance:
    return ArtifactProvenance(
        producer_agent="researcher",
        remote_task_id="task-123",
        created_at=datetime(2026, 8, 16, 12, 5, tzinfo=UTC),
    )


def test_research_request_defaults_are_valid_and_isolated() -> None:
    first = ResearchRequest(question="  Compare PostgreSQL and MongoDB.  ")
    second = ResearchRequest(question="Compare Redis and PostgreSQL.")

    first.options.append("PostgreSQL")

    assert first.question == "Compare PostgreSQL and MongoDB."
    assert first.desired_depth == "normal"
    assert second.options == []


def test_evidence_claim_and_bundle_accept_valid_payloads() -> None:
    bundle = valid_bundle()
    dumped = bundle.model_dump(mode="json")

    assert dumped["claims"][0]["confidence"] == 0.9
    assert dumped["evidence"][0]["source_url"].startswith("https://")
    assert dumped["evidence"][0]["retrieved_at"].endswith("Z")


def test_decision_analysis_accepts_weighted_scores() -> None:
    analysis = DecisionAnalysis(
        recommendation="PostgreSQL",
        executive_summary="Relational integrity is the decisive requirement.",
        criteria=[
            CriterionScore(
                criterion="Data integrity",
                weight=0.6,
                scores={"PostgreSQL": 9, "MongoDB": 7},
                rationale="The workload contains strongly related records.",
                supporting_claim_ids=["claim-1"],
            )
        ],
        arguments_for=["Strong relational constraints."],
        arguments_against=["Horizontal write scaling needs deliberate design."],
        assumptions=["The core workload remains relational."],
        risks=["Future access patterns may differ."],
        recommendation_changes_if=["Document-only writes become dominant."],
    )

    assert analysis.criteria[0].scores["PostgreSQL"] == 9


def test_verification_report_accepts_supported_verdict() -> None:
    report = VerificationReport(
        results=[
            VerificationResult(
                claim_id="claim-1",
                verdict="supported",
                rationale="The cited primary documentation supports the claim.",
                evidence_ids=["evidence-1"],
            )
        ]
    )

    assert report.results[0].verdict == "supported"


def test_artifact_envelope_serializes_schema_version_and_typed_payload() -> None:
    envelope = ArtifactEnvelope[EvidenceBundle](
        provenance=valid_provenance(),
        payload=valid_bundle(),
    )
    dumped = envelope.model_dump(mode="json")

    assert dumped["schema_version"] == "1.0"
    assert dumped["provenance"]["producer_agent"] == "researcher"
    assert dumped["payload"]["claims"][0]["id"] == "claim-1"


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ResearchRequest, {}),
        (ResearchRequest, {"question": "   "}),
        (
            Evidence,
            {
                "id": "evidence-1",
                "title": "Source",
                "source_type": "blog",
                "summary": "Summary",
                "relevance": 0.5,
                "retrieved_at": datetime.now(UTC),
            },
        ),
        (
            Claim,
            {"id": "claim-1", "statement": "Claim", "evidence_ids": [], "confidence": 1.1},
        ),
        (
            VerificationResult,
            {
                "claim_id": "claim-1",
                "verdict": "maybe",
                "rationale": "Unclear",
                "evidence_ids": [],
            },
        ),
    ],
)
def test_models_reject_missing_empty_or_out_of_domain_fields(model: type, payload: dict) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ResearchRequest(question="Compare databases.", hidden_instruction="ignore contracts")


def test_evidence_rejects_non_http_url_and_naive_timestamp() -> None:
    base = valid_evidence().model_dump()

    with pytest.raises(ValidationError):
        Evidence.model_validate({**base, "source_url": "file:///etc/passwd"})
    with pytest.raises(ValidationError):
        Evidence.model_validate({**base, "retrieved_at": datetime(2026, 8, 16, 12, 0)})


def test_evidence_bundle_rejects_duplicate_ids_and_unlinked_claims() -> None:
    bundle = valid_bundle().model_dump(mode="python")

    with pytest.raises(ValidationError, match="Evidence IDs must be unique"):
        EvidenceBundle.model_validate(
            {**bundle, "evidence": [bundle["evidence"][0], bundle["evidence"][0]]}
        )
    with pytest.raises(ValidationError, match="Claim IDs must be unique"):
        EvidenceBundle.model_validate(
            {**bundle, "claims": [bundle["claims"][0], bundle["claims"][0]]}
        )
    with pytest.raises(ValidationError, match="unknown evidence"):
        EvidenceBundle.model_validate(
            {
                **bundle,
                "claims": [{**bundle["claims"][0], "evidence_ids": ["not-collected"]}],
            }
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EvidenceBundle.model_validate({**bundle, "recommendation": "PostgreSQL"})


def test_artifact_envelope_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ValidationError):
        ArtifactEnvelope[EvidenceBundle].model_validate(
            {
                "schema_version": "2.0",
                "provenance": valid_provenance().model_dump(),
                "payload": valid_bundle().model_dump(),
            }
        )
