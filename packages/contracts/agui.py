"""Versioned application contracts carried through AG-UI runs and state events."""

import re
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    AwareDatetime,
    Field,
    RootModel,
    StringConstraints,
    model_validator,
)

from packages.contracts.base import MAX_BOUNDED_TEXT_LENGTH, ContractModel
from packages.contracts.domain import (
    Claim,
    DecisionAnalysis,
    Depth,
    Evidence,
    RecommendationChallenge,
    VerificationReport,
)
from packages.contracts.intake import IntakeResponse

AG_UI_STATE_SCHEMA_VERSION: Literal["1.0"] = "1.0"
AG_UI_ACTION_SCHEMA_VERSION: Literal["1.0"] = "1.0"
MAX_AG_UI_TEXT_LENGTH = MAX_BOUNDED_TEXT_LENGTH
MAX_AG_UI_ACTION_LIST_LENGTH = 20
AgUiText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_AG_UI_TEXT_LENGTH,
    ),
]


def _camelize(value: Any, *, transform_keys: bool = True) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = (
                key.split("_")[0] + "".join(part.capitalize() for part in key.split("_")[1:])
                if transform_keys
                else key
            )
            result[normalized_key] = _camelize(
                item,
                transform_keys=key not in {"scores", "answers"},
            )
        return result
    if isinstance(value, list):
        return [_camelize(item, transform_keys=transform_keys) for item in value]
    return value


def _snakeize(value: Any, *, transform_keys: bool = True) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower() if transform_keys else key
            result[normalized_key] = _snakeize(
                item,
                transform_keys=key not in {"scores", "answers"},
            )
        return result
    if isinstance(value, list):
        return [_snakeize(item, transform_keys=transform_keys) for item in value]
    return value


SessionStatus = Literal[
    "idle",
    "scoping",
    "awaiting_input",
    "planning",
    "researching",
    "analyzing",
    "verifying",
    "cancelling",
    "completed",
    "cancelled",
    "failed",
    "partial",
]
SpecialistStatus = Literal[
    "pending",
    "working",
    "waiting",
    "completed",
    "cancelled",
    "failed",
]
ActionType = Literal[
    "prepare_research",
    "submit_intake",
    "skip_intake",
    "start_research",
    "challenge_recommendation",
    "research_deeper",
    "focus_on_criterion",
    "retry_failed_agent",
]
FollowUpActionType = Literal[
    "submit_intake",
    "skip_intake",
    "challenge_recommendation",
    "research_deeper",
    "focus_on_criterion",
    "retry_failed_agent",
]


class SpecialistView(ContractModel):
    """Renderable status for one independently deployed specialist."""

    agent_id: AgUiText = Field(
        validation_alias=AliasChoices("agentId", "agent_id"),
        serialization_alias="agentId",
    )
    name: AgUiText
    skill: AgUiText
    status: SpecialistStatus
    remote_task_id: AgUiText | None = Field(
        default=None,
        validation_alias=AliasChoices("remoteTaskId", "remote_task_id"),
        serialization_alias="remoteTaskId",
    )
    message: AgUiText | None = None


class AgentDeskViewState(ContractModel):
    """Validated state snapshot rendered by the trusted React application."""

    schema_version: Literal["1.0"] = Field(
        default=AG_UI_STATE_SCHEMA_VERSION,
        validation_alias=AliasChoices("schemaVersion", "schema_version"),
        serialization_alias="schemaVersion",
    )
    session_id: AgUiText | None = Field(
        default=None,
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    question: AgUiText | None = None
    status: SessionStatus = "idle"
    active_step: AgUiText | None = Field(
        default=None,
        validation_alias=AliasChoices("activeStep", "active_step"),
        serialization_alias="activeStep",
    )
    agents: list[SpecialistView] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_count: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("evidenceCount", "evidence_count"),
        serialization_alias="evidenceCount",
    )
    claims: list[Claim] = Field(default_factory=list)
    analysis: DecisionAnalysis | None = None
    recommendation_challenge: RecommendationChallenge | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "recommendationChallenge",
            "recommendation_challenge",
        ),
        serialization_alias="recommendationChallenge",
    )
    verification: VerificationReport | None = None
    warnings: list[AgUiText] = Field(default_factory=list)
    errors: list[AgUiText] = Field(default_factory=list)
    available_actions: list[FollowUpActionType] = Field(
        default_factory=list,
        validation_alias=AliasChoices("availableActions", "available_actions"),
        serialization_alias="availableActions",
    )
    last_updated_at: AwareDatetime | None = Field(
        default=None,
        validation_alias=AliasChoices("lastUpdatedAt", "last_updated_at"),
        serialization_alias="lastUpdatedAt",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_camel_case(cls, value: Any) -> Any:
        return _snakeize(value)

    @model_validator(mode="after")
    def validate_consistency(self) -> AgentDeskViewState:
        if self.status != "idle" and (
            self.session_id is None or self.question is None or self.last_updated_at is None
        ):
            raise ValueError("Active AG-UI state requires session, question, and update timestamp.")
        if self.evidence_count != len(self.evidence):
            raise ValueError("evidenceCount must equal the number of evidence items.")
        agent_ids = [agent.agent_id for agent in self.agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("Agent IDs must be unique within AG-UI state.")
        evidence_ids = [evidence.id for evidence in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evidence IDs must be unique within AG-UI state.")
        claim_ids = [claim.id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Claim IDs must be unique within AG-UI state.")
        known_evidence = set(evidence_ids)
        for claim in self.claims:
            if unknown := set(claim.evidence_ids) - known_evidence:
                raise ValueError(f"Claim {claim.id} references unknown evidence: {sorted(unknown)}")
        if len(self.available_actions) != len(set(self.available_actions)):
            raise ValueError("Available actions must not contain duplicates.")
        if self.status == "failed" and not self.errors:
            raise ValueError("Failed AG-UI state requires at least one user-visible error.")
        return self

    def to_ag_ui(self) -> dict[str, object]:
        """Serialize with the camelCase field names consumed by AG-UI clients."""
        serialized = _camelize(self.model_dump(mode="json"))
        if not isinstance(serialized, dict):  # pragma: no cover - model dumps are dictionaries
            raise TypeError("AG-UI state serialization must produce an object.")
        return serialized


class StartResearchPayload(ContractModel):
    question: AgUiText
    options: list[AgUiText] = Field(default_factory=list, max_length=MAX_AG_UI_ACTION_LIST_LENGTH)
    constraints: list[AgUiText] = Field(
        default_factory=list, max_length=MAX_AG_UI_ACTION_LIST_LENGTH
    )
    criteria: list[AgUiText] = Field(default_factory=list, max_length=MAX_AG_UI_ACTION_LIST_LENGTH)
    desired_depth: Depth = Field(
        default="normal",
        validation_alias=AliasChoices("desiredDepth", "desired_depth"),
        serialization_alias="desiredDepth",
    )


class PrepareResearchPayload(StartResearchPayload):
    """Potentially incomplete request that may require adaptive intake."""


class SubmitIntakePayload(ContractModel):
    response: IntakeResponse

    @model_validator(mode="before")
    @classmethod
    def normalize_response_camel_case(cls, value: Any) -> Any:
        return _snakeize(value)


class SkipIntakePayload(ContractModel):
    """Explicit request to continue with proposal defaults."""


class ChallengeRecommendationPayload(ContractModel):
    challenge: AgUiText | None = None


class ResearchDeeperPayload(ContractModel):
    focus_areas: list[AgUiText] = Field(
        default_factory=list,
        max_length=MAX_AG_UI_ACTION_LIST_LENGTH,
        validation_alias=AliasChoices("focusAreas", "focus_areas"),
        serialization_alias="focusAreas",
    )
    desired_depth: Literal["normal", "deep"] = Field(
        default="deep",
        validation_alias=AliasChoices("desiredDepth", "desired_depth"),
        serialization_alias="desiredDepth",
    )


class FocusOnCriterionPayload(ContractModel):
    criterion: AgUiText


class RetryFailedAgentPayload(ContractModel):
    agent_id: AgUiText = Field(
        validation_alias=AliasChoices("agentId", "agent_id"),
        serialization_alias="agentId",
    )
    remote_task_id: AgUiText | None = Field(
        default=None,
        validation_alias=AliasChoices("remoteTaskId", "remote_task_id"),
        serialization_alias="remoteTaskId",
    )


class _ActionBase(ContractModel):
    schema_version: Literal["1.0"] = Field(
        default=AG_UI_ACTION_SCHEMA_VERSION,
        validation_alias=AliasChoices("schemaVersion", "schema_version"),
        serialization_alias="schemaVersion",
    )
    action_id: AgUiText = Field(
        validation_alias=AliasChoices("actionId", "action_id"),
        serialization_alias="actionId",
    )


class StartResearchAction(_ActionBase):
    type: Literal["start_research"]
    session_id: None = Field(
        default=None,
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    payload: StartResearchPayload


class PrepareResearchAction(_ActionBase):
    type: Literal["prepare_research"]
    session_id: None = Field(
        default=None,
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    payload: PrepareResearchPayload


class SubmitIntakeAction(_ActionBase):
    type: Literal["submit_intake"]
    session_id: AgUiText = Field(
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    payload: SubmitIntakePayload


class SkipIntakeAction(_ActionBase):
    type: Literal["skip_intake"]
    session_id: AgUiText = Field(
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    payload: SkipIntakePayload = Field(default_factory=SkipIntakePayload)


class ChallengeRecommendationAction(_ActionBase):
    type: Literal["challenge_recommendation"]
    session_id: AgUiText = Field(
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    payload: ChallengeRecommendationPayload


class ResearchDeeperAction(_ActionBase):
    type: Literal["research_deeper"]
    session_id: AgUiText = Field(
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    payload: ResearchDeeperPayload


class FocusOnCriterionAction(_ActionBase):
    type: Literal["focus_on_criterion"]
    session_id: AgUiText = Field(
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    payload: FocusOnCriterionPayload


class RetryFailedAgentAction(_ActionBase):
    type: Literal["retry_failed_agent"]
    session_id: AgUiText = Field(
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    payload: RetryFailedAgentPayload


ActionEnvelope = Annotated[
    PrepareResearchAction
    | SubmitIntakeAction
    | SkipIntakeAction
    | StartResearchAction
    | ChallengeRecommendationAction
    | ResearchDeeperAction
    | FocusOnCriterionAction
    | RetryFailedAgentAction,
    Field(discriminator="type"),
]


class AgentDeskAction(RootModel[ActionEnvelope]):
    """Strict discriminated action envelope supplied in AG-UI forwarded props."""

    root: ActionEnvelope

    def to_ag_ui(self) -> dict[str, object]:
        serialized = _camelize(self.root.model_dump(mode="json"))
        if not isinstance(serialized, dict):  # pragma: no cover - model dumps are dictionaries
            raise TypeError("AG-UI action serialization must produce an object.")
        return serialized
