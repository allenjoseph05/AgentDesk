"""Core AgentDesk research, analysis, and verification payloads."""

from typing import Annotated, Literal

from pydantic import AnyHttpUrl, AwareDatetime, Field, FiniteFloat, model_validator

from packages.contracts.base import ContractModel, NonEmptyText

Depth = Literal["fast", "normal", "deep"]
AnalysisMode = Literal["compare_options", "challenge_current_recommendation"]
SourceType = Literal[
    "official_documentation",
    "primary_source",
    "secondary_source",
    "user_provided",
    "fixture",
]
VerificationVerdict = Literal[
    "supported",
    "partially_supported",
    "contradicted",
    "insufficient_evidence",
]
UnitInterval = Annotated[FiniteFloat, Field(ge=0, le=1)]
OptionScore = Annotated[FiniteFloat, Field(ge=0, le=10)]


class ResearchRequest(ContractModel):
    """Validated input supplied to the research workflow."""

    question: NonEmptyText
    options: list[NonEmptyText] = Field(default_factory=list)
    constraints: list[NonEmptyText] = Field(default_factory=list)
    criteria: list[NonEmptyText] = Field(default_factory=list)
    desired_depth: Depth = "normal"


class Evidence(ContractModel):
    """One traceable source collected during research."""

    id: NonEmptyText
    title: NonEmptyText
    source_url: AnyHttpUrl | None = None
    source_type: SourceType
    summary: NonEmptyText
    relevance: UnitInterval
    retrieved_at: AwareDatetime


class Claim(ContractModel):
    """A research claim linked to supporting evidence identifiers."""

    id: NonEmptyText
    statement: NonEmptyText
    evidence_ids: list[NonEmptyText] = Field(min_length=1)
    confidence: UnitInterval | None = None
    caveats: list[NonEmptyText] = Field(default_factory=list)


class EvidenceBundle(ContractModel):
    """Typed output produced by the Research Agent."""

    question: NonEmptyText
    claims: list[Claim]
    evidence: list[Evidence]
    unknowns: list[NonEmptyText]
    research_notes: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_links(self) -> "EvidenceBundle":
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evidence IDs must be unique within a bundle.")

        claim_ids = [claim.id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Claim IDs must be unique within a bundle.")

        known_evidence = set(evidence_ids)
        for claim in self.claims:
            if unknown := set(claim.evidence_ids) - known_evidence:
                raise ValueError(f"Claim {claim.id} references unknown evidence: {sorted(unknown)}")
        return self


class AnalysisRequest(ContractModel):
    """Evidence and decision context supplied to the Analyst Agent."""

    question: NonEmptyText
    options: list[NonEmptyText] = Field(min_length=2, max_length=4)
    constraints: list[NonEmptyText] = Field(default_factory=list)
    criteria: list[NonEmptyText] = Field(min_length=1)
    evidence_bundle: EvidenceBundle
    mode: AnalysisMode = "compare_options"
    current_recommendation: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_decision_context(self) -> "AnalysisRequest":
        normalized_options = [option.casefold() for option in self.options]
        if len(normalized_options) != len(set(normalized_options)):
            raise ValueError("Analysis options must be unique.")

        normalized_criteria = [criterion.casefold() for criterion in self.criteria]
        if len(normalized_criteria) != len(set(normalized_criteria)):
            raise ValueError("Analysis criteria must be unique.")

        if self.question.casefold() != self.evidence_bundle.question.casefold():
            raise ValueError("Analysis question must match the evidence bundle question.")
        if self.mode == "challenge_current_recommendation":
            if self.current_recommendation is None:
                raise ValueError("Challenge mode requires the current recommendation.")
            if self.current_recommendation not in self.options:
                raise ValueError("Current recommendation must be one of the supplied options.")
        elif self.current_recommendation is not None:
            raise ValueError("Current recommendation is only valid in challenge mode.")
        return self


class CriterionScore(ContractModel):
    """Weighted scores and their evidence-backed rationale."""

    criterion: NonEmptyText
    weight: UnitInterval
    scores: dict[NonEmptyText, OptionScore]
    rationale: NonEmptyText
    supporting_claim_ids: list[NonEmptyText]


class DecisionAnalysis(ContractModel):
    """Structured comparison and recommendation from the Analyst Agent."""

    recommendation: NonEmptyText
    executive_summary: NonEmptyText
    criteria: list[CriterionScore] = Field(min_length=1)
    arguments_for: list[NonEmptyText] = Field(min_length=1)
    arguments_against: list[NonEmptyText] = Field(min_length=1)
    assumptions: list[NonEmptyText] = Field(min_length=1)
    risks: list[NonEmptyText] = Field(min_length=1)
    recommendation_changes_if: list[NonEmptyText] = Field(min_length=1)


class RecommendationChallenge(ContractModel):
    """Evidence-bound strongest case against an existing recommendation."""

    current_recommendation: NonEmptyText
    strongest_alternative: NonEmptyText
    strongest_counterargument: NonEmptyText
    supporting_claim_ids: list[NonEmptyText] = Field(min_length=1)
    assumptions: list[NonEmptyText] = Field(min_length=1)
    evidence_gaps: list[NonEmptyText] = Field(default_factory=list)
    recommendation_changes_if: list[NonEmptyText] = Field(min_length=1)


class VerificationResult(ContractModel):
    """Verdict for one claim and its supporting evidence references."""

    claim_id: NonEmptyText
    verdict: VerificationVerdict
    rationale: NonEmptyText
    evidence_ids: list[NonEmptyText]


class VerificationReport(ContractModel):
    """Typed output produced by the Verifier Agent."""

    results: list[VerificationResult]
