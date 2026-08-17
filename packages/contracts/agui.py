"""Application state exposed to the browser through AG-UI events."""

from typing import Literal

from pydantic import Field

from packages.contracts.base import ContractModel, NonEmptyText

AG_UI_STATE_SCHEMA_VERSION = "1.0"
SessionStatus = Literal[
    "idle",
    "planning",
    "researching",
    "analyzing",
    "verifying",
    "completed",
    "cancelled",
    "failed",
    "partial",
]


class AgentDeskViewState(ContractModel):
    """Validated state snapshot rendered by the trusted React application."""

    schema_version: Literal["1.0"] = Field(
        default=AG_UI_STATE_SCHEMA_VERSION,
        serialization_alias="schemaVersion",
    )
    session_id: NonEmptyText | None = Field(default=None, serialization_alias="sessionId")
    question: NonEmptyText | None = None
    status: SessionStatus = "idle"
    active_step: NonEmptyText | None = Field(default=None, serialization_alias="activeStep")
    evidence_count: int = Field(default=0, ge=0, serialization_alias="evidenceCount")
    warnings: list[NonEmptyText] = Field(default_factory=list)
    errors: list[NonEmptyText] = Field(default_factory=list)

    def to_ag_ui(self) -> dict[str, object]:
        """Serialize with the camelCase field names consumed by AG-UI clients."""
        return self.model_dump(mode="json", by_alias=True)
