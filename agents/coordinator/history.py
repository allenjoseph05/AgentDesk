"""Persistence-backed session history and terminal-state rehydration."""

from __future__ import annotations

from pydantic import AliasChoices, AwareDatetime, Field, field_serializer

from agents.coordinator.projection import DurableAgUiProjector
from packages.contracts import AgentDeskViewState
from packages.contracts.base import ContractModel, NonEmptyText
from packages.persistence import Database
from packages.persistence.records import SessionPersistenceStatus, SessionRecord

TERMINAL_SESSION_STATUSES = {"completed", "partial", "failed", "cancelled"}


class SessionHistoryNotFoundError(LookupError):
    """The requested session does not exist."""


class SessionHistoryNotReadyError(RuntimeError):
    """The requested session has not reached a rehydratable terminal state."""


class SessionHistoryItem(ContractModel):
    """Compact durable session metadata rendered in the history sidebar."""

    session_id: NonEmptyText = Field(
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    thread_id: NonEmptyText = Field(
        validation_alias=AliasChoices("threadId", "thread_id"),
        serialization_alias="threadId",
    )
    question: NonEmptyText
    status: SessionPersistenceStatus
    last_run_id: NonEmptyText | None = Field(
        default=None,
        validation_alias=AliasChoices("lastRunId", "last_run_id"),
        serialization_alias="lastRunId",
    )
    created_at: AwareDatetime = Field(
        validation_alias=AliasChoices("createdAt", "created_at"),
        serialization_alias="createdAt",
    )
    updated_at: AwareDatetime = Field(
        validation_alias=AliasChoices("updatedAt", "updated_at"),
        serialization_alias="updatedAt",
    )


class SessionHistoryPage(ContractModel):
    """Bounded recent-session result returned to the web application."""

    sessions: list[SessionHistoryItem]


class SessionHistoryDetail(ContractModel):
    """Terminal session metadata plus its fully reconstructed AG-UI state."""

    session: SessionHistoryItem
    state: AgentDeskViewState

    @field_serializer("state")
    def serialize_state(self, state: AgentDeskViewState) -> dict[str, object]:
        return state.to_ag_ui()


class ResearchHistoryService:
    """Read prior sessions without executing any Coordinator or specialist work."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._projector = DurableAgUiProjector(database)

    def list_sessions(
        self,
        *,
        limit: int = 50,
        thread_id: str | None = None,
        owner_id: str = "local-development",
    ) -> SessionHistoryPage:
        if limit < 1 or limit > 100:
            raise ValueError("Session history limit must be between 1 and 100.")
        with self._database.transaction() as repositories:
            records = repositories.sessions.list_recent(
                limit=limit,
                owner_id=owner_id,
                ag_ui_thread_id=thread_id,
            )
        return SessionHistoryPage(
            sessions=[_history_item(record) for record in records]
        )

    def get_terminal_session(
        self,
        session_id: str,
        *,
        owner_id: str = "local-development",
    ) -> SessionHistoryDetail:
        with self._database.transaction() as repositories:
            session = repositories.sessions.get(session_id)
        if session is None or session.owner_id != owner_id:
            raise SessionHistoryNotFoundError(session_id)
        if session.status not in TERMINAL_SESSION_STATUSES:
            raise SessionHistoryNotReadyError(session_id)
        return SessionHistoryDetail(
            session=_history_item(session),
            state=self._projector.snapshot(session_id),
        )


def _history_item(record: SessionRecord) -> SessionHistoryItem:
    return SessionHistoryItem(
        session_id=record.id,
        thread_id=record.ag_ui_thread_id,
        question=record.question,
        status=record.status,
        last_run_id=record.last_run_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
