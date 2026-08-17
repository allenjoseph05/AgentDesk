"""Versioned cross-agent contracts."""

from packages.contracts.agui import (
    AG_UI_ACTION_SCHEMA_VERSION,
    AG_UI_STATE_SCHEMA_VERSION,
    ActionType,
    AgentDeskAction,
    AgentDeskViewState,
    SpecialistView,
)
from packages.contracts.artifacts import (
    DOMAIN_SCHEMA_VERSION,
    ArtifactEnvelope,
    ArtifactProvenance,
)
from packages.contracts.domain import (
    AnalysisRequest,
    Claim,
    CriterionScore,
    DecisionAnalysis,
    Evidence,
    EvidenceBundle,
    RecommendationChallenge,
    ResearchRequest,
    VerificationReport,
    VerificationResult,
)

__all__ = [
    "AG_UI_ACTION_SCHEMA_VERSION",
    "AG_UI_STATE_SCHEMA_VERSION",
    "ActionType",
    "AgentDeskAction",
    "AgentDeskViewState",
    "DOMAIN_SCHEMA_VERSION",
    "ArtifactEnvelope",
    "ArtifactProvenance",
    "AnalysisRequest",
    "Claim",
    "CriterionScore",
    "DecisionAnalysis",
    "Evidence",
    "EvidenceBundle",
    "RecommendationChallenge",
    "ResearchRequest",
    "SpecialistView",
    "VerificationReport",
    "VerificationResult",
]
