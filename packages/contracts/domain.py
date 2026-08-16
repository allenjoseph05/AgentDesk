"""Core AgentDesk research, analysis, and verification payloads."""

from typing import Annotated, Literal

from pydantic import AnyHttpUrl, AwareDatetime, Field, FiniteFloat

from packages.contracts.base import ContractModel, NonEmptyText

Depth = Literal["fast", "normal", "deep"]
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
NonNegativeFloat = Annotated[FiniteFloat, Field(ge=0)]


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
    evidence_ids: list[NonEmptyText]
    confidence: UnitInterval | None = None
    caveats: list[NonEmptyText] = Field(default_factory=list)


class EvidenceBundle(ContractModel):
    """Typed output produced by the Research Agent."""

    question: NonEmptyText
    claims: list[Claim]
    evidence: list[Evidence]
    unknowns: list[NonEmptyText]
    research_notes: list[NonEmptyText] = Field(default_factory=list)


class CriterionScore(ContractModel):
    """Weighted scores and their evidence-backed rationale."""

    criterion: NonEmptyText
    weight: NonNegativeFloat
    scores: dict[NonEmptyText, FiniteFloat]
    rationale: NonEmptyText
    supporting_claim_ids: list[NonEmptyText]


class DecisionAnalysis(ContractModel):
    """Structured comparison and recommendation from the Analyst Agent."""

    recommendation: NonEmptyText
    executive_summary: NonEmptyText
    criteria: list[CriterionScore]
    arguments_for: list[NonEmptyText]
    arguments_against: list[NonEmptyText]
    assumptions: list[NonEmptyText]
    risks: list[NonEmptyText]
    recommendation_changes_if: list[NonEmptyText]


class VerificationResult(ContractModel):
    """Verdict for one claim and its supporting evidence references."""

    claim_id: NonEmptyText
    verdict: VerificationVerdict
    rationale: NonEmptyText
    evidence_ids: list[NonEmptyText]


class VerificationReport(ContractModel):
    """Typed output produced by the Verifier Agent."""

    results: list[VerificationResult]
