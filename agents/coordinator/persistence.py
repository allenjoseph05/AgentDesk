"""Coordinator-owned durable workflow and specialist artifact persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from agents.coordinator.workflow_state import WorkflowSnapshot, WorkflowTransition
from packages.contracts import ArtifactEnvelope, DecisionAnalysis, EvidenceBundle
from packages.persistence import (
    AgentTaskRecord,
    AnalysisRecord,
    ClaimRecord,
    CoordinatorRunRecord,
    Database,
    EvidenceRecord,
    RepositoryConflictError,
    ResearchArtifactRecord,
    SessionRecord,
    WorkflowTransitionRecord,
)


class WorkflowPersistenceError(RuntimeError):
    """A durable workflow write does not agree with the recorded workflow."""


class ArtifactProvenanceError(WorkflowPersistenceError):
    """An artifact cannot be correlated to its durable specialist task."""


@dataclass(frozen=True)
class EvidencePersistenceResult:
    evidence_inserted: int
    claims_inserted: int
    bundle_inserted: bool = False


class WorkflowPersistenceService:
    """Persist Coordinator commit points behind one transaction boundary."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def initialize(
        self,
        *,
        snapshot: WorkflowSnapshot,
        ag_ui_thread_id: str,
        run_id: str,
        action_id: str,
        action_type: str,
        question: str,
    ) -> None:
        session = _session_record(
            snapshot,
            ag_ui_thread_id=ag_ui_thread_id,
            question=question,
            created_at=snapshot.updated_at,
            last_run_id=run_id,
            last_action_id=action_id,
        )
        run = CoordinatorRunRecord(
            run_id=run_id,
            session_id=snapshot.session_id,
            ag_ui_thread_id=ag_ui_thread_id,
            action_id=action_id,
            action_type=action_type,
            started_at=snapshot.updated_at,
        )
        with self._database.transaction() as repositories:
            repositories.sessions.add(session)
            repositories.runs.add(run)

    def continue_session(
        self,
        *,
        session_id: str,
        ag_ui_thread_id: str,
        run_id: str,
        action_id: str,
        action_type: str,
        started_at: datetime,
    ) -> None:
        """Attach a new Coordinator run to an existing browser session."""
        run = CoordinatorRunRecord(
            run_id=run_id,
            session_id=session_id,
            ag_ui_thread_id=ag_ui_thread_id,
            action_id=action_id,
            action_type=action_type,
            started_at=started_at,
        )
        with self._database.transaction() as repositories:
            session = repositories.sessions.require(session_id)
            if session.ag_ui_thread_id != ag_ui_thread_id:
                raise WorkflowPersistenceError(
                    "Coordinator session does not belong to the AG-UI thread."
                )
            if started_at < session.updated_at:
                raise WorkflowPersistenceError(
                    "Coordinator run timestamp precedes durable session state."
                )
            repositories.runs.add(run)
            repositories.sessions.replace(
                session.model_copy(
                    update={
                        "last_run_id": run_id,
                        "last_action_id": action_id,
                        "updated_at": started_at,
                    }
                )
            )

    def start_run(self, run_id: str) -> bool:
        """Advance one accepted Coordinator run to its execution boundary."""
        with self._database.transaction() as repositories:
            current = repositories.runs.get(run_id)
            if current is None:
                raise WorkflowPersistenceError(
                    f"Coordinator run {run_id} does not exist."
                )
            if current.status == "running":
                return False
            if current.status != "accepted":
                raise WorkflowPersistenceError(
                    f"Coordinator run {run_id} is already terminal."
                )
            repositories.runs.replace(current.model_copy(update={"status": "running"}))
            return True

    def finish_run(
        self,
        run_id: str,
        *,
        status: Literal["completed", "partial", "failed", "cancelled"],
        finished_at: datetime,
    ) -> bool:
        """Persist one terminal Coordinator run result; exact replay is harmless."""
        with self._database.transaction() as repositories:
            current = repositories.runs.get(run_id)
            if current is None:
                raise WorkflowPersistenceError(
                    f"Coordinator run {run_id} does not exist."
                )
            replacement = CoordinatorRunRecord.model_validate(
                current.model_copy(
                    update={"status": status, "finished_at": finished_at}
                ).model_dump(mode="python")
            )
            if current.status in {"completed", "partial", "failed", "cancelled"}:
                if current != replacement:
                    raise RepositoryConflictError("coordinator run outcome", run_id)
                return False
            repositories.runs.replace(replacement)
            return True

    def persist_transition(
        self,
        snapshot: WorkflowSnapshot,
        transition: WorkflowTransition,
    ) -> bool:
        """Atomically append a transition and advance the session snapshot."""
        _validate_transition_projection(snapshot, transition)
        record = WorkflowTransitionRecord(
            session_id=snapshot.session_id,
            **transition.model_dump(mode="python"),
        )
        with self._database.transaction() as repositories:
            current = repositories.sessions.require(snapshot.session_id)
            existing = repositories.transitions.get(
                snapshot.session_id,
                transition.sequence,
            )
            if existing is not None:
                repositories.transitions.put(record)
                if not _session_matches_snapshot(current, snapshot):
                    raise WorkflowPersistenceError(
                        "Replayed transition does not match the durable session state."
                    )
                return False

            history = repositories.transitions.list_by_session(snapshot.session_id)
            if transition.sequence != len(history) + 1:
                raise WorkflowPersistenceError("Workflow transition sequence is not contiguous.")
            if transition.from_status != current.status:
                raise WorkflowPersistenceError(
                    "Workflow transition source does not match durable session state."
                )
            if transition.occurred_at < current.updated_at:
                raise WorkflowPersistenceError(
                    "Workflow transition timestamp precedes durable session state."
                )

            repositories.transitions.put(record)
            repositories.sessions.replace(
                _session_record(
                    snapshot,
                    ag_ui_thread_id=current.ag_ui_thread_id,
                    question=current.question,
                    created_at=current.created_at,
                    last_run_id=current.last_run_id,
                    last_action_id=current.last_action_id,
                )
            )
            return True

    def create_agent_task(self, task: AgentTaskRecord) -> None:
        with self._database.transaction() as repositories:
            repositories.sessions.require(task.session_id)
            repositories.agent_tasks.add(task)

    def finish_agent_task(
        self,
        task_id: str,
        *,
        status: Literal["completed", "failed", "cancelled"],
        finished_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        """Record one terminal specialist outcome; an exact replay is harmless."""
        with self._database.transaction() as repositories:
            current = repositories.agent_tasks.require(task_id)
            replacement = current.model_copy(
                update={
                    "status": status,
                    "finished_at": finished_at,
                    "error_code": error_code,
                    "error_message": error_message,
                }
            )
            replacement = AgentTaskRecord.model_validate(
                replacement.model_dump(mode="python")
            )
            if current.status in {"completed", "failed", "cancelled"}:
                if current != replacement:
                    raise RepositoryConflictError("agent task outcome", task_id)
                return False
            repositories.agent_tasks.replace(replacement)
            return True

    def register_remote_task(
        self,
        task_id: str,
        *,
        remote_task_id: str,
        a2a_context_id: str | None = None,
    ) -> bool:
        """Persist A2A correlation once; exact callback replay is harmless."""
        with self._database.transaction() as repositories:
            current = repositories.agent_tasks.require(task_id)
            if current.remote_task_id is not None:
                if current.remote_task_id != remote_task_id:
                    raise RepositoryConflictError("agent task correlation", task_id)
                if (
                    current.a2a_context_id is not None
                    and a2a_context_id is not None
                    and current.a2a_context_id != a2a_context_id
                ):
                    raise RepositoryConflictError("agent task correlation", task_id)
                if current.a2a_context_id is not None or a2a_context_id is None:
                    return False
                repositories.agent_tasks.replace(
                    current.model_copy(update={"a2a_context_id": a2a_context_id})
                )
                return True
            if current.a2a_context_id not in {None, a2a_context_id}:
                raise RepositoryConflictError("agent task correlation", task_id)
            repositories.agent_tasks.replace(
                current.model_copy(
                    update={
                        "remote_task_id": remote_task_id,
                        "a2a_context_id": a2a_context_id,
                        "status": "submitted",
                    }
                )
            )
            return True

    def persist_evidence(
        self,
        session_id: str,
        task_id: str,
        envelope: ArtifactEnvelope[EvidenceBundle],
    ) -> EvidencePersistenceResult:
        with self._database.transaction() as repositories:
            task = repositories.agent_tasks.require(task_id)
            _validate_provenance(session_id, task, envelope)
            bundle_inserted = repositories.artifacts.put_research_artifact(
                ResearchArtifactRecord(
                    id=_artifact_row_id(session_id, "research-artifact", task_id),
                    session_id=session_id,
                    agent_task_id=task_id,
                    envelope=envelope,
                )
            )
            evidence_inserted = sum(
                repositories.artifacts.put_evidence(
                    EvidenceRecord(
                        id=_artifact_row_id(session_id, "evidence", item.id),
                        session_id=session_id,
                        agent_task_id=task_id,
                        evidence=item,
                        artifact_schema_version=envelope.schema_version,
                    )
                )
                for item in envelope.payload.evidence
            )
            claims_inserted = sum(
                repositories.artifacts.put_claim(
                    ClaimRecord(
                        id=_artifact_row_id(session_id, "claim", item.id),
                        session_id=session_id,
                        agent_task_id=task_id,
                        claim=item,
                        artifact_schema_version=envelope.schema_version,
                    )
                )
                for item in envelope.payload.claims
            )
        return EvidencePersistenceResult(evidence_inserted, claims_inserted, bundle_inserted)

    def persist_analysis(
        self,
        session_id: str,
        task_id: str,
        envelope: ArtifactEnvelope[DecisionAnalysis],
    ) -> bool:
        with self._database.transaction() as repositories:
            task = repositories.agent_tasks.require(task_id)
            _validate_provenance(session_id, task, envelope)
            return repositories.artifacts.put_analysis(
                AnalysisRecord(
                    id=_artifact_row_id(session_id, "analysis", task_id),
                    session_id=session_id,
                    agent_task_id=task_id,
                    analysis=envelope.payload,
                    artifact_schema_version=envelope.schema_version,
                    created_at=envelope.provenance.created_at,
                )
            )


def _session_record(
    snapshot: WorkflowSnapshot,
    *,
    ag_ui_thread_id: str,
    question: str,
    created_at: datetime,
    last_run_id: str | None,
    last_action_id: str | None,
) -> SessionRecord:
    return SessionRecord(
        id=snapshot.session_id,
        ag_ui_thread_id=ag_ui_thread_id,
        last_run_id=last_run_id,
        last_action_id=last_action_id,
        question=question,
        status=snapshot.status,
        active_step=snapshot.active_step,
        completed_steps=snapshot.completed_steps,
        failed_steps=snapshot.failed_steps,
        created_at=created_at,
        updated_at=snapshot.updated_at,
    )


def _validate_transition_projection(
    snapshot: WorkflowSnapshot,
    transition: WorkflowTransition,
) -> None:
    if (
        transition.to_status != snapshot.status
        or transition.active_step != snapshot.active_step
        or transition.occurred_at != snapshot.updated_at
    ):
        raise WorkflowPersistenceError(
            "Workflow transition does not describe the candidate session snapshot."
        )


def _session_matches_snapshot(
    session: SessionRecord,
    snapshot: WorkflowSnapshot,
) -> bool:
    return (
        session.status == snapshot.status
        and session.active_step == snapshot.active_step
        and session.completed_steps == snapshot.completed_steps
        and session.failed_steps == snapshot.failed_steps
        and session.updated_at == snapshot.updated_at
    )


def _validate_provenance(
    session_id: str,
    task: AgentTaskRecord,
    envelope: ArtifactEnvelope[Any],
) -> None:
    provenance = envelope.provenance
    if task.session_id != session_id:
        raise ArtifactProvenanceError("Artifact session does not match its agent task.")
    if task.remote_task_id is None:
        raise ArtifactProvenanceError("Agent task has no durable remote task identity.")
    if provenance.remote_task_id != task.remote_task_id:
        raise ArtifactProvenanceError("Artifact remote task identity does not match.")
    if provenance.producer_agent != task.agent_id:
        raise ArtifactProvenanceError("Artifact producer does not match its agent task.")


def _artifact_row_id(session_id: str, kind: str, identity: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"agentdesk:{session_id}:{kind}:{identity}"))
