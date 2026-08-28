"""Coordinator-owned durable workflow and specialist artifact persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from agents.coordinator.intake import compile_research_request
from agents.coordinator.workflow_state import WorkflowSnapshot, WorkflowTransition
from packages.contracts import (
    ArtifactEnvelope,
    DecisionAnalysis,
    EvidenceBundle,
    IntakeResponse,
    RecommendationChallenge,
    ResearchRequest,
    ScopeProposalArtifact,
    ScopingRequest,
    VerificationReport,
)
from packages.limits import LimitExceededError
from packages.persistence import (
    AgentTaskRecord,
    AnalysisRecord,
    ClaimRecord,
    CoordinatorRunRecord,
    Database,
    EvidenceRecord,
    IntakeProposalRecord,
    IntakeResponseRecord,
    RecommendationChallengeRecord,
    RepositoryConflictError,
    ResearchArtifactRecord,
    SessionRecord,
    VerificationReportRecord,
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


@dataclass(frozen=True)
class FollowUpContext:
    question: str
    options: tuple[str, ...]
    criteria: tuple[str, ...]
    evidence_bundle: EvidenceBundle
    current_recommendation: str


class WorkflowPersistenceService:
    """Persist Coordinator commit points behind one transaction boundary."""

    def __init__(
        self,
        database: Database,
        *,
        max_remote_tasks_per_session: int | None = None,
    ) -> None:
        self._database = database
        self._max_remote_tasks_per_session = max_remote_tasks_per_session

    def ensure_remote_task_capacity(
        self,
        session_id: str,
        additional_tasks: int,
    ) -> None:
        """Reject fan-out that would cross the durable per-session task maximum."""
        if additional_tasks < 1:
            raise ValueError("Additional remote tasks must be positive.")
        maximum = self._max_remote_tasks_per_session
        if maximum is None:
            return
        with self._database.transaction() as repositories:
            repositories.sessions.require(session_id)
            existing = len(repositories.agent_tasks.list_by_session(session_id))
        if existing + additional_tasks <= maximum:
            return
        raise LimitExceededError(
            "remote_task_limit_exceeded",
            "This session reached its remote-task limit. Start a new session or ask an "
            "administrator to raise the configured maximum.",
        )

    def load_follow_up_context(self, session_id: str) -> FollowUpContext:
        """Rehydrate the latest accepted decision context for a follow-up run."""
        with self._database.transaction() as repositories:
            repositories.sessions.require(session_id)
            research = repositories.artifacts.list_research_artifacts(session_id)
            analyses = repositories.artifacts.list_analysis(session_id)
        if not research or not analyses:
            raise WorkflowPersistenceError(
                "Follow-up actions require completed research and analysis."
            )
        latest_analysis = analyses[-1].analysis
        options = tuple(
            dict.fromkeys(
                option for criterion in latest_analysis.criteria for option in criterion.scores
            )
        )
        criteria = tuple(item.criterion for item in latest_analysis.criteria)
        if len(options) < 2 or not criteria:
            raise WorkflowPersistenceError(
                "The durable analysis does not contain reusable decision context."
            )
        latest_research = research[-1].envelope.payload
        return FollowUpContext(
            question=latest_research.question,
            options=options,
            criteria=criteria,
            evidence_bundle=latest_research,
            current_recommendation=latest_analysis.recommendation,
        )

    def load_workflow(
        self,
        session_id: str,
    ) -> tuple[WorkflowSnapshot, tuple[WorkflowTransition, ...]]:
        """Rehydrate a state machine from its committed session and transitions."""
        with self._database.transaction() as repositories:
            session = repositories.sessions.require(session_id)
            records = repositories.transitions.list_by_session(session_id)
        snapshot = WorkflowSnapshot(
            session_id=session.id,
            status=session.status,
            active_step=session.active_step,
            completed_steps=session.completed_steps,
            failed_steps=session.failed_steps,
            updated_at=session.updated_at,
        )
        history = tuple(
            WorkflowTransition.model_validate(record.model_dump(exclude={"session_id"}))
            for record in records
        )
        return snapshot, history

    def persist_intake_proposal(
        self,
        *,
        session_id: str,
        agent_task_id: str,
        request: ScopingRequest,
        artifact: ScopeProposalArtifact,
    ) -> bool:
        """Persist one scoper artifact only after validating its task provenance."""
        record = IntakeProposalRecord(
            proposal_id=artifact.payload.proposal_id,
            session_id=session_id,
            agent_task_id=agent_task_id,
            request=request,
            artifact=artifact,
            created_at=artifact.provenance.created_at,
        )
        with self._database.transaction() as repositories:
            task = repositories.agent_tasks.require(agent_task_id)
            if task.session_id != session_id or task.skill != "decision-scoping":
                raise ArtifactProvenanceError(
                    "Intake artifact does not belong to its scoping task."
                )
            if task.remote_task_id != artifact.provenance.remote_task_id:
                raise ArtifactProvenanceError("Intake artifact task provenance does not match.")
            existing = repositories.intake.get_proposal(record.proposal_id)
            if existing is not None:
                if existing != record:
                    raise RepositoryConflictError("intake proposal", record.proposal_id)
                return False
            repositories.intake.add_proposal(record)
            return True

    def accept_intake_response(
        self,
        *,
        session_id: str,
        action_id: str,
        response: IntakeResponse,
        decided_at: datetime,
    ) -> ResearchRequest:
        """Validate, normalize, and commit a response and proposal decision atomically."""
        with self._database.transaction() as repositories:
            proposal = repositories.intake.get_proposal_by_session(session_id)
            if proposal is None:
                raise WorkflowPersistenceError("Coordinator session has no intake proposal.")
            normalized = compile_research_request(
                proposal.request,
                proposal.artifact.payload,
                response,
            )
            record = IntakeResponseRecord(
                action_id=action_id,
                session_id=session_id,
                proposal_id=proposal.proposal_id,
                response=response,
                normalized_request=normalized,
                created_at=decided_at,
            )
            if proposal.status != "awaiting_response":
                existing = repositories.intake.get_response_by_proposal(proposal.proposal_id)
                if proposal.status == "accepted" and existing == record:
                    return normalized
                raise RepositoryConflictError("intake decision", proposal.proposal_id)
            repositories.intake.put_response(record)
            repositories.intake.replace_proposal(
                proposal.model_copy(
                    update={
                        "status": "accepted",
                        "normalized_request": normalized,
                        "decided_at": decided_at,
                    }
                )
            )
            return normalized

    def skip_intake(
        self,
        *,
        session_id: str,
        decided_at: datetime,
    ) -> ResearchRequest:
        """Commit an explicit skip using only trusted proposal defaults."""
        with self._database.transaction() as repositories:
            proposal = repositories.intake.get_proposal_by_session(session_id)
            if proposal is None:
                raise WorkflowPersistenceError("Coordinator session has no intake proposal.")
            normalized = compile_research_request(
                proposal.request,
                proposal.artifact.payload,
                None,
            )
            if proposal.status != "awaiting_response":
                if proposal.status == "skipped" and proposal.normalized_request == normalized:
                    return normalized
                raise RepositoryConflictError("intake decision", proposal.proposal_id)
            repositories.intake.replace_proposal(
                proposal.model_copy(
                    update={
                        "status": "skipped",
                        "normalized_request": normalized,
                        "decided_at": decided_at,
                    }
                )
            )
            return normalized

    def load_intake_proposal(self, session_id: str) -> IntakeProposalRecord | None:
        with self._database.transaction() as repositories:
            repositories.sessions.require(session_id)
            return repositories.intake.get_proposal_by_session(session_id)

    def initialize(
        self,
        *,
        snapshot: WorkflowSnapshot,
        ag_ui_thread_id: str,
        run_id: str,
        action_id: str,
        action_type: str,
        question: str,
        owner_id: str = "local-development",
    ) -> None:
        session = _session_record(
            snapshot,
            owner_id=owner_id,
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
        owner_id: str = "local-development",
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
            if session.owner_id != owner_id:
                raise WorkflowPersistenceError(
                    "Coordinator session does not belong to the authenticated principal."
                )
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
                raise WorkflowPersistenceError(f"Coordinator run {run_id} does not exist.")
            if current.status == "running":
                return False
            if current.status != "accepted":
                raise WorkflowPersistenceError(f"Coordinator run {run_id} is already terminal.")
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
                raise WorkflowPersistenceError(f"Coordinator run {run_id} does not exist.")
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
                    owner_id=current.owner_id,
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
            maximum = self._max_remote_tasks_per_session
            existing = repositories.agent_tasks.list_by_session(task.session_id)
            if maximum is not None and len(existing) >= maximum:
                raise LimitExceededError(
                    "remote_task_limit_exceeded",
                    "This session reached its remote-task limit. Start a new session or "
                    "ask an administrator to raise the configured maximum.",
                )
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
            replacement = AgentTaskRecord.model_validate(replacement.model_dump(mode="python"))
            if current.status in {"completed", "failed", "cancelled"}:
                if current != replacement:
                    raise RepositoryConflictError("agent task outcome", task_id)
                return False
            repositories.agent_tasks.replace(replacement)
            return True

    def cancel_run_agent_tasks(
        self,
        *,
        session_id: str,
        run_id: str,
        finished_at: datetime,
    ) -> tuple[str, ...]:
        """Make every non-terminal specialist task in one run durably cancelled."""
        cancelled: list[str] = []
        with self._database.transaction() as repositories:
            run = repositories.runs.get(run_id)
            if run is None or run.session_id != session_id:
                raise WorkflowPersistenceError(
                    "Coordinator run does not belong to the cancellation session."
                )
            for task in repositories.agent_tasks.list_by_session(session_id):
                if task.run_id != run_id or task.status in {
                    "completed",
                    "failed",
                    "cancelled",
                }:
                    continue
                repositories.agent_tasks.replace(
                    AgentTaskRecord.model_validate(
                        task.model_copy(
                            update={
                                "status": "cancelled",
                                "finished_at": finished_at,
                            }
                        ).model_dump(mode="python")
                    )
                )
                cancelled.append(task.id)
        return tuple(cancelled)

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
                        "status": (
                            current.status
                            if current.status in {"completed", "failed", "cancelled"}
                            else "submitted"
                        ),
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

    def persist_recommendation_challenge(
        self,
        session_id: str,
        task_id: str,
        envelope: ArtifactEnvelope[RecommendationChallenge],
    ) -> bool:
        with self._database.transaction() as repositories:
            task = repositories.agent_tasks.require(task_id)
            _validate_provenance(session_id, task, envelope)
            return repositories.artifacts.put_recommendation_challenge(
                RecommendationChallengeRecord(
                    id=_artifact_row_id(
                        session_id,
                        "recommendation-challenge",
                        task_id,
                    ),
                    session_id=session_id,
                    agent_task_id=task_id,
                    envelope=envelope,
                )
            )

    def persist_verification_report(
        self,
        session_id: str,
        task_id: str,
        envelope: ArtifactEnvelope[VerificationReport],
    ) -> bool:
        with self._database.transaction() as repositories:
            task = repositories.agent_tasks.require(task_id)
            _validate_provenance(session_id, task, envelope)
            claim_ids = {
                record.claim.id for record in repositories.artifacts.list_claims(session_id)
            }
            evidence_ids = {
                record.evidence.id for record in repositories.artifacts.list_evidence(session_id)
            }
            _validate_verification_report(envelope.payload, claim_ids, evidence_ids)
            return repositories.artifacts.put_verification_report(
                VerificationReportRecord(
                    id=_artifact_row_id(session_id, "verification-report", task_id),
                    session_id=session_id,
                    agent_task_id=task_id,
                    envelope=envelope,
                )
            )


def _session_record(
    snapshot: WorkflowSnapshot,
    *,
    owner_id: str,
    ag_ui_thread_id: str,
    question: str,
    created_at: datetime,
    last_run_id: str | None,
    last_action_id: str | None,
) -> SessionRecord:
    return SessionRecord(
        id=snapshot.session_id,
        owner_id=owner_id,
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


def _validate_verification_report(
    report: VerificationReport,
    claim_ids: set[str],
    evidence_ids: set[str],
) -> None:
    result_claim_ids = [result.claim_id for result in report.results]
    if len(result_claim_ids) != len(set(result_claim_ids)):
        raise WorkflowPersistenceError("Verification report repeats a claim verdict.")
    if set(result_claim_ids) != claim_ids:
        raise WorkflowPersistenceError(
            "Verification report must cover every durable claim exactly once."
        )
    for result in report.results:
        if not result.evidence_ids:
            raise WorkflowPersistenceError(
                f"Verification result for {result.claim_id} has no evidence reference."
            )
        if len(result.evidence_ids) != len(set(result.evidence_ids)):
            raise WorkflowPersistenceError(
                f"Verification result for {result.claim_id} repeats evidence references."
            )
        if unknown := set(result.evidence_ids) - evidence_ids:
            raise WorkflowPersistenceError(
                f"Verification report references unknown evidence: {sorted(unknown)}"
            )


def _artifact_row_id(session_id: str, kind: str, identity: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"agentdesk:{session_id}:{kind}:{identity}"))
