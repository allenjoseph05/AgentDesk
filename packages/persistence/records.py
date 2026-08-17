"""Typed records exchanged with the AgentDesk repository layer."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from packages.contracts import Claim, DecisionAnalysis, Evidence
from packages.contracts.base import ContractModel, NonEmptyText

SessionPersistenceStatus = Literal[
    "created",
    "planning",
    "researching",
    "analyzing",
    "verifying",
    "cancelling",
    "completed",
    "partial",
    "failed",
    "cancelled",
]
RunPersistenceStatus = Literal[
    "accepted",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
]
AgentTaskPersistenceStatus = Literal[
    "pending",
    "submitted",
    "working",
    "completed",
    "failed",
    "cancelled",
]


class SessionRecord(ContractModel):
    id: NonEmptyText
    ag_ui_thread_id: NonEmptyText
    last_run_id: NonEmptyText | None = None
    last_action_id: NonEmptyText | None = None
    state_schema_version: NonEmptyText = "1.0"
    question: NonEmptyText
    status: SessionPersistenceStatus = "created"
    active_step: NonEmptyText | None = None
    completed_steps: list[NonEmptyText] = Field(default_factory=list)
    failed_steps: list[NonEmptyText] = Field(default_factory=list)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_state(self) -> SessionRecord:
        active = {
            "planning",
            "researching",
            "analyzing",
            "verifying",
            "cancelling",
        }
        terminal = {"completed", "partial", "failed", "cancelled"}
        if self.status in active and self.active_step is None:
            raise ValueError("Active session requires an active step.")
        if self.status in terminal and self.active_step is not None:
            raise ValueError("Terminal session cannot retain an active step.")
        return self


class CoordinatorRunRecord(ContractModel):
    run_id: NonEmptyText
    session_id: NonEmptyText
    ag_ui_thread_id: NonEmptyText
    action_id: NonEmptyText
    action_type: NonEmptyText
    status: RunPersistenceStatus = "accepted"
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_finish_timestamp(self) -> CoordinatorRunRecord:
        terminal = {"completed", "partial", "failed", "cancelled"}
        if self.status in terminal and self.finished_at is None:
            raise ValueError("Terminal Coordinator run requires a finish timestamp.")
        if self.status not in terminal and self.finished_at is not None:
            raise ValueError("Active Coordinator run cannot have a finish timestamp.")
        return self


class AgentTaskRecord(ContractModel):
    id: NonEmptyText
    session_id: NonEmptyText
    run_id: NonEmptyText | None = None
    agent_id: NonEmptyText
    skill: NonEmptyText
    a2a_context_id: NonEmptyText | None = None
    remote_task_id: NonEmptyText | None = None
    status: AgentTaskPersistenceStatus = "pending"
    error_code: NonEmptyText | None = None
    error_message: NonEmptyText | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_terminal_fields(self) -> AgentTaskRecord:
        if self.status == "failed" and self.error_code is None:
            raise ValueError("Failed agent task requires an error code.")
        if self.status in {"completed", "failed", "cancelled"} and self.finished_at is None:
            raise ValueError("Terminal agent task requires a finish timestamp.")
        return self


class EvidenceRecord(ContractModel):
    id: NonEmptyText
    session_id: NonEmptyText
    agent_task_id: NonEmptyText | None = None
    evidence: Evidence
    artifact_schema_version: NonEmptyText


class ClaimRecord(ContractModel):
    id: NonEmptyText
    session_id: NonEmptyText
    agent_task_id: NonEmptyText | None = None
    claim: Claim
    artifact_schema_version: NonEmptyText


class AnalysisRecord(ContractModel):
    id: NonEmptyText
    session_id: NonEmptyText
    agent_task_id: NonEmptyText | None = None
    analysis: DecisionAnalysis
    artifact_schema_version: NonEmptyText
    created_at: AwareDatetime
