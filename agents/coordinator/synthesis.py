"""Deterministic final synthesis from authoritative specialist artifacts."""

from __future__ import annotations

from packages.contracts import (
    ArtifactEnvelope,
    DecisionAnalysis,
    EvidenceBundle,
    FinalSynthesis,
)


class SynthesisError(RuntimeError):
    """Typed refusal to manufacture a final result from incomplete artifacts."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SynthesisService:
    """Assemble final output without redoing specialist reasoning."""

    def synthesize(
        self,
        *,
        question: str,
        evidence_artifact: ArtifactEnvelope[EvidenceBundle] | None,
        analysis_artifact: ArtifactEnvelope[DecisionAnalysis] | None,
    ) -> FinalSynthesis:
        if evidence_artifact is None:
            raise SynthesisError(
                "missing_evidence",
                "Final synthesis requires the Research evidence artifact.",
            )
        if analysis_artifact is None:
            raise SynthesisError(
                "missing_analysis",
                "Final synthesis requires the Analyst decision artifact.",
            )

        evidence_envelope = ArtifactEnvelope[EvidenceBundle].model_validate(
            evidence_artifact.model_dump(mode="python")
        )
        analysis_envelope = ArtifactEnvelope[DecisionAnalysis].model_validate(
            analysis_artifact.model_dump(mode="python")
        )
        evidence = evidence_envelope.payload
        analysis = analysis_envelope.payload
        normalized_question = question.strip()
        if not normalized_question:
            raise SynthesisError("invalid_question", "Final synthesis question cannot be blank.")
        if evidence.question.casefold() != normalized_question.casefold():
            raise SynthesisError(
                "question_mismatch",
                "Research evidence does not belong to the synthesis question.",
            )
        if not evidence.evidence or not evidence.claims:
            raise SynthesisError(
                "missing_evidence",
                "Final synthesis will not replace an empty evidence artifact.",
            )

        known_claim_ids = {claim.id for claim in evidence.claims}
        supporting_claim_ids = _supporting_claim_ids(analysis)
        unknown_claim_ids = set(supporting_claim_ids) - known_claim_ids
        if unknown_claim_ids:
            raise SynthesisError(
                "unsupported_analysis",
                f"Analysis references claims absent from Research: {sorted(unknown_claim_ids)}",
            )
        if not supporting_claim_ids:
            raise SynthesisError(
                "ungrounded_analysis",
                "Final synthesis requires at least one evidence-backed analysis criterion.",
            )

        return FinalSynthesis(
            question=normalized_question,
            summary=analysis.executive_summary,
            recommendation=analysis.recommendation,
            assumptions=list(analysis.assumptions),
            warnings=_warnings(evidence, analysis),
            supporting_claim_ids=supporting_claim_ids,
            evidence_count=len(evidence.evidence),
            research_task_id=evidence_envelope.provenance.remote_task_id,
            analysis_task_id=analysis_envelope.provenance.remote_task_id,
        )


def _supporting_claim_ids(analysis: DecisionAnalysis) -> list[str]:
    claim_ids: list[str] = []
    for criterion in analysis.criteria:
        for claim_id in criterion.supporting_claim_ids:
            if claim_id not in claim_ids:
                claim_ids.append(claim_id)
    return claim_ids


def _warnings(evidence: EvidenceBundle, analysis: DecisionAnalysis) -> list[str]:
    warnings: list[str] = []
    entries = [
        *(("Evidence gap", item) for item in evidence.unknowns),
        *(("Claim caveat", caveat) for claim in evidence.claims for caveat in claim.caveats),
        *(("Research note", item) for item in evidence.research_notes),
        *(("Decision risk", item) for item in analysis.risks),
    ]
    for category, message in entries:
        warning = f"{category}: {message}"
        if warning not in warnings:
            warnings.append(warning)
    return warnings
