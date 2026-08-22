"""SQLAlchemy repository implementations for durable AgentDesk records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError

from packages.contracts import (
    ArtifactEnvelope,
    ArtifactProvenance,
    Claim,
    DecisionAnalysis,
    Evidence,
    EvidenceBundle,
    RecommendationChallenge,
    VerificationReport,
)
from packages.persistence.records import (
    AgentTaskRecord,
    AnalysisRecord,
    ClaimRecord,
    CoordinatorRunRecord,
    EvidenceRecord,
    RecommendationChallengeRecord,
    ResearchArtifactRecord,
    SessionRecord,
    VerificationReportRecord,
    WorkflowTransitionRecord,
)
from packages.persistence.schema import (
    agent_tasks,
    analysis,
    claims,
    coordinator_runs,
    evidence,
    recommendation_challenges,
    research_artifacts,
    sessions,
    verification_reports,
    workflow_transitions,
)


class RepositoryError(RuntimeError):
    """Base failure exposed by persistence repositories."""


class RecordNotFoundError(RepositoryError):
    def __init__(self, entity: str, record_id: str) -> None:
        self.entity = entity
        self.record_id = record_id
        super().__init__(f"{entity} record {record_id} does not exist.")


class RepositoryConflictError(RepositoryError):
    def __init__(self, entity: str, record_id: str) -> None:
        self.entity = entity
        self.record_id = record_id
        super().__init__(f"{entity} record {record_id} conflicts with existing data.")


class _Repository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _insert(
        self,
        table: sa.Table,
        values: dict[str, Any],
        *,
        entity: str,
        record_id: str,
    ) -> None:
        try:
            self._connection.execute(sa.insert(table).values(**values))
        except IntegrityError as error:
            raise RepositoryConflictError(entity, record_id) from error

    def _require_update(
        self,
        statement: sa.Update,
        *,
        entity: str,
        record_id: str,
    ) -> None:
        result = self._connection.execute(statement)
        if result.rowcount != 1:
            raise RecordNotFoundError(entity, record_id)

    def _insert_if_absent(
        self,
        table: sa.Table,
        values: dict[str, Any],
        *,
        conflict_columns: tuple[str, ...],
    ) -> bool:
        dialect = self._connection.dialect.name
        if dialect == "sqlite":
            sqlite_statement = sqlite_insert(table).values(**values).on_conflict_do_nothing(
                index_elements=list(conflict_columns)
            )
            return self._connection.execute(sqlite_statement).rowcount == 1
        if dialect == "postgresql":
            postgresql_statement = (
                postgresql_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=list(conflict_columns))
            )
            return self._connection.execute(postgresql_statement).rowcount == 1

        try:
            with self._connection.begin_nested():
                self._connection.execute(sa.insert(table).values(**values))
            return True
        except IntegrityError:
            return False


class SessionRepository(_Repository):
    def add(self, record: SessionRecord) -> None:
        validated = SessionRecord.model_validate(record.model_dump(mode="python"))
        self._insert(
            sessions,
            validated.model_dump(mode="python"),
            entity="session",
            record_id=validated.id,
        )

    def get(self, session_id: str) -> SessionRecord | None:
        row = self._connection.execute(
            sa.select(sessions).where(sessions.c.id == session_id)
        ).mappings().one_or_none()
        return _session_record(row) if row is not None else None

    def require(self, session_id: str) -> SessionRecord:
        record = self.get(session_id)
        if record is None:
            raise RecordNotFoundError("session", session_id)
        return record

    def replace(self, record: SessionRecord) -> None:
        validated = SessionRecord.model_validate(record.model_dump(mode="python"))
        current = self.require(validated.id)
        _assert_immutable(
            "session",
            validated.id,
            current,
            validated,
            ("ag_ui_thread_id", "question", "created_at"),
        )
        values = validated.model_dump(
            mode="python",
            exclude={"id", "ag_ui_thread_id", "question", "created_at"},
        )
        self._require_update(
            sa.update(sessions).where(sessions.c.id == validated.id).values(**values),
            entity="session",
            record_id=validated.id,
        )

    def list_by_thread(self, ag_ui_thread_id: str) -> tuple[SessionRecord, ...]:
        rows = self._connection.execute(
            sa.select(sessions)
            .where(sessions.c.ag_ui_thread_id == ag_ui_thread_id)
            .order_by(sessions.c.updated_at.desc(), sessions.c.id)
        ).mappings()
        return tuple(_session_record(row) for row in rows)

    def list_recent(
        self,
        *,
        limit: int = 50,
        ag_ui_thread_id: str | None = None,
    ) -> tuple[SessionRecord, ...]:
        if limit < 1:
            raise ValueError("Session history limit must be positive.")
        statement = sa.select(sessions)
        if ag_ui_thread_id is not None:
            statement = statement.where(
                sessions.c.ag_ui_thread_id == ag_ui_thread_id
            )
        rows = self._connection.execute(
            statement.order_by(sessions.c.updated_at.desc(), sessions.c.id).limit(limit)
        ).mappings()
        return tuple(_session_record(row) for row in rows)


class CoordinatorRunRepository(_Repository):
    def add(self, record: CoordinatorRunRecord) -> None:
        validated = CoordinatorRunRecord.model_validate(record.model_dump(mode="python"))
        self._insert(
            coordinator_runs,
            validated.model_dump(mode="python"),
            entity="coordinator run",
            record_id=validated.run_id,
        )

    def get(self, run_id: str) -> CoordinatorRunRecord | None:
        row = self._connection.execute(
            sa.select(coordinator_runs).where(coordinator_runs.c.run_id == run_id)
        ).mappings().one_or_none()
        return _run_record(row) if row is not None else None

    def get_by_action(self, action_id: str) -> CoordinatorRunRecord | None:
        row = self._connection.execute(
            sa.select(coordinator_runs).where(coordinator_runs.c.action_id == action_id)
        ).mappings().one_or_none()
        return _run_record(row) if row is not None else None

    def replace(self, record: CoordinatorRunRecord) -> None:
        validated = CoordinatorRunRecord.model_validate(record.model_dump(mode="python"))
        current = self.get(validated.run_id)
        if current is None:
            raise RecordNotFoundError("coordinator run", validated.run_id)
        _assert_immutable(
            "coordinator run",
            validated.run_id,
            current,
            validated,
            (
                "session_id",
                "ag_ui_thread_id",
                "action_id",
                "action_type",
                "started_at",
            ),
        )
        values = validated.model_dump(
            mode="python",
            exclude={
                "run_id",
                "session_id",
                "ag_ui_thread_id",
                "action_id",
                "action_type",
                "started_at",
            },
        )
        self._require_update(
            sa.update(coordinator_runs)
            .where(coordinator_runs.c.run_id == validated.run_id)
            .values(**values),
            entity="coordinator run",
            record_id=validated.run_id,
        )


class WorkflowTransitionRepository(_Repository):
    def put(self, record: WorkflowTransitionRecord) -> bool:
        validated = WorkflowTransitionRecord.model_validate(
            record.model_dump(mode="python")
        )
        existing = self.get(validated.session_id, validated.sequence)
        if existing is not None:
            _assert_same(
                "workflow transition", _transition_id(validated), existing, validated
            )
            return False
        inserted = self._insert_if_absent(
            workflow_transitions,
            validated.model_dump(mode="python"),
            conflict_columns=("session_id", "sequence"),
        )
        if not inserted:
            existing = self.get(validated.session_id, validated.sequence)
            if existing is None:
                raise RepositoryConflictError(
                    "workflow transition", _transition_id(validated)
                )
            _assert_same(
                "workflow transition", _transition_id(validated), existing, validated
            )
        return inserted

    def get(
        self,
        session_id: str,
        sequence: int,
    ) -> WorkflowTransitionRecord | None:
        row = self._connection.execute(
            sa.select(workflow_transitions).where(
                workflow_transitions.c.session_id == session_id,
                workflow_transitions.c.sequence == sequence,
            )
        ).mappings().one_or_none()
        return _workflow_transition_record(row) if row is not None else None

    def list_by_session(self, session_id: str) -> tuple[WorkflowTransitionRecord, ...]:
        rows = self._connection.execute(
            sa.select(workflow_transitions)
            .where(workflow_transitions.c.session_id == session_id)
            .order_by(workflow_transitions.c.sequence)
        ).mappings()
        return tuple(_workflow_transition_record(row) for row in rows)

class AgentTaskRepository(_Repository):
    def add(self, record: AgentTaskRecord) -> None:
        validated = AgentTaskRecord.model_validate(record.model_dump(mode="python"))
        self._insert(
            agent_tasks,
            validated.model_dump(mode="python"),
            entity="agent task",
            record_id=validated.id,
        )

    def get(self, task_id: str) -> AgentTaskRecord | None:
        row = self._connection.execute(
            sa.select(agent_tasks).where(agent_tasks.c.id == task_id)
        ).mappings().one_or_none()
        return _agent_task_record(row) if row is not None else None

    def require(self, task_id: str) -> AgentTaskRecord:
        record = self.get(task_id)
        if record is None:
            raise RecordNotFoundError("agent task", task_id)
        return record

    def get_by_remote(
        self,
        *,
        agent_id: str,
        remote_task_id: str,
    ) -> AgentTaskRecord | None:
        row = self._connection.execute(
            sa.select(agent_tasks).where(
                agent_tasks.c.agent_id == agent_id,
                agent_tasks.c.remote_task_id == remote_task_id,
            )
        ).mappings().one_or_none()
        return _agent_task_record(row) if row is not None else None

    def replace(self, record: AgentTaskRecord) -> None:
        validated = AgentTaskRecord.model_validate(record.model_dump(mode="python"))
        current = self.get(validated.id)
        if current is None:
            raise RecordNotFoundError("agent task", validated.id)
        _assert_immutable(
            "agent task",
            validated.id,
            current,
            validated,
            ("session_id", "run_id", "agent_id", "skill", "started_at"),
        )
        values = validated.model_dump(
            mode="python",
            exclude={"id", "session_id", "run_id", "agent_id", "skill", "started_at"},
        )
        self._require_update(
            sa.update(agent_tasks)
            .where(agent_tasks.c.id == validated.id)
            .values(**values),
            entity="agent task",
            record_id=validated.id,
        )

    def list_by_session(self, session_id: str) -> tuple[AgentTaskRecord, ...]:
        rows = self._connection.execute(
            sa.select(agent_tasks)
            .where(agent_tasks.c.session_id == session_id)
            .order_by(agent_tasks.c.started_at, agent_tasks.c.id)
        ).mappings()
        return tuple(_agent_task_record(row) for row in rows)


class ArtifactRepository(_Repository):
    def put_research_artifact(self, record: ResearchArtifactRecord) -> bool:
        validated = ResearchArtifactRecord.model_validate(record.model_dump(mode="python"))
        existing = self.get_research_artifact_by_task(validated.agent_task_id)
        if existing is not None:
            _assert_same("research artifact", validated.id, existing, validated)
            return False
        inserted = self._insert_if_absent(
            research_artifacts,
            _research_artifact_values(validated),
            conflict_columns=("agent_task_id",),
        )
        if not inserted:
            existing = self.get_research_artifact_by_task(validated.agent_task_id)
            if existing is None:
                raise RepositoryConflictError("research artifact", validated.id)
            _assert_same("research artifact", validated.id, existing, validated)
        return inserted

    def get_research_artifact_by_task(
        self,
        agent_task_id: str,
    ) -> ResearchArtifactRecord | None:
        row = self._connection.execute(
            sa.select(research_artifacts).where(
                research_artifacts.c.agent_task_id == agent_task_id
            )
        ).mappings().one_or_none()
        return _research_artifact_record(row) if row is not None else None

    def list_research_artifacts(
        self,
        session_id: str,
    ) -> tuple[ResearchArtifactRecord, ...]:
        rows = self._connection.execute(
            sa.select(research_artifacts)
            .where(research_artifacts.c.session_id == session_id)
            .order_by(research_artifacts.c.created_at, research_artifacts.c.id)
        ).mappings()
        return tuple(_research_artifact_record(row) for row in rows)

    def put_recommendation_challenge(
        self,
        record: RecommendationChallengeRecord,
    ) -> bool:
        validated = RecommendationChallengeRecord.model_validate(
            record.model_dump(mode="python")
        )
        existing = self.get_recommendation_challenge_by_task(validated.agent_task_id)
        if existing is not None:
            _assert_same("recommendation challenge", validated.id, existing, validated)
            return False
        inserted = self._insert_if_absent(
            recommendation_challenges,
            _recommendation_challenge_values(validated),
            conflict_columns=("agent_task_id",),
        )
        if not inserted:
            existing = self.get_recommendation_challenge_by_task(validated.agent_task_id)
            if existing is None:
                raise RepositoryConflictError("recommendation challenge", validated.id)
            _assert_same("recommendation challenge", validated.id, existing, validated)
        return inserted

    def get_recommendation_challenge_by_task(
        self,
        agent_task_id: str,
    ) -> RecommendationChallengeRecord | None:
        row = self._connection.execute(
            sa.select(recommendation_challenges).where(
                recommendation_challenges.c.agent_task_id == agent_task_id
            )
        ).mappings().one_or_none()
        return _recommendation_challenge_record(row) if row is not None else None

    def list_recommendation_challenges(
        self,
        session_id: str,
    ) -> tuple[RecommendationChallengeRecord, ...]:
        rows = self._connection.execute(
            sa.select(recommendation_challenges)
            .where(recommendation_challenges.c.session_id == session_id)
            .order_by(
                recommendation_challenges.c.created_at,
                recommendation_challenges.c.id,
            )
        ).mappings()
        return tuple(_recommendation_challenge_record(row) for row in rows)

    def put_verification_report(self, record: VerificationReportRecord) -> bool:
        validated = VerificationReportRecord.model_validate(
            record.model_dump(mode="python")
        )
        existing = self.get_verification_report_by_task(validated.agent_task_id)
        if existing is not None:
            _assert_same("verification report", validated.id, existing, validated)
            return False
        inserted = self._insert_if_absent(
            verification_reports,
            _verification_report_values(validated),
            conflict_columns=("agent_task_id",),
        )
        if not inserted:
            existing = self.get_verification_report_by_task(validated.agent_task_id)
            if existing is None:
                raise RepositoryConflictError("verification report", validated.id)
            _assert_same("verification report", validated.id, existing, validated)
        return inserted

    def get_verification_report_by_task(
        self,
        agent_task_id: str,
    ) -> VerificationReportRecord | None:
        row = self._connection.execute(
            sa.select(verification_reports).where(
                verification_reports.c.agent_task_id == agent_task_id
            )
        ).mappings().one_or_none()
        return _verification_report_record(row) if row is not None else None

    def list_verification_reports(
        self,
        session_id: str,
    ) -> tuple[VerificationReportRecord, ...]:
        rows = self._connection.execute(
            sa.select(verification_reports)
            .where(verification_reports.c.session_id == session_id)
            .order_by(verification_reports.c.created_at, verification_reports.c.id)
        ).mappings()
        return tuple(_verification_report_record(row) for row in rows)

    def add_evidence(self, record: EvidenceRecord) -> None:
        validated = EvidenceRecord.model_validate(record.model_dump(mode="python"))
        self._insert(
            evidence,
            _evidence_values(validated),
            entity="evidence",
            record_id=validated.id,
        )

    def put_evidence(self, record: EvidenceRecord) -> bool:
        validated = EvidenceRecord.model_validate(record.model_dump(mode="python"))
        existing = self.get_evidence(validated.session_id, validated.evidence.id)
        if existing is not None:
            _assert_reusable_artifact("evidence", validated.id, existing, validated)
            return False
        inserted = self._insert_if_absent(
            evidence,
            _evidence_values(validated),
            conflict_columns=("session_id", "evidence_id"),
        )
        if not inserted:
            existing = self.get_evidence(validated.session_id, validated.evidence.id)
            if existing is None:
                raise RepositoryConflictError("evidence", validated.id)
            _assert_reusable_artifact("evidence", validated.id, existing, validated)
        return inserted

    def get_evidence(
        self,
        session_id: str,
        evidence_id: str,
    ) -> EvidenceRecord | None:
        row = self._connection.execute(
            sa.select(evidence).where(
                evidence.c.session_id == session_id,
                evidence.c.evidence_id == evidence_id,
            )
        ).mappings().one_or_none()
        return _evidence_record(row) if row is not None else None

    def list_evidence(self, session_id: str) -> tuple[EvidenceRecord, ...]:
        rows = self._connection.execute(
            sa.select(evidence)
            .where(evidence.c.session_id == session_id)
            .order_by(evidence.c.retrieved_at, evidence.c.evidence_id)
        ).mappings()
        return tuple(_evidence_record(row) for row in rows)

    def add_claim(self, record: ClaimRecord) -> None:
        validated = ClaimRecord.model_validate(record.model_dump(mode="python"))
        self._insert(
            claims,
            _claim_values(validated),
            entity="claim",
            record_id=validated.id,
        )

    def put_claim(self, record: ClaimRecord) -> bool:
        validated = ClaimRecord.model_validate(record.model_dump(mode="python"))
        existing = self.get_claim(validated.session_id, validated.claim.id)
        if existing is not None:
            _assert_reusable_artifact("claim", validated.id, existing, validated)
            return False
        inserted = self._insert_if_absent(
            claims,
            _claim_values(validated),
            conflict_columns=("session_id", "claim_id"),
        )
        if not inserted:
            existing = self.get_claim(validated.session_id, validated.claim.id)
            if existing is None:
                raise RepositoryConflictError("claim", validated.id)
            _assert_reusable_artifact("claim", validated.id, existing, validated)
        return inserted

    def get_claim(self, session_id: str, claim_id: str) -> ClaimRecord | None:
        row = self._connection.execute(
            sa.select(claims).where(
                claims.c.session_id == session_id,
                claims.c.claim_id == claim_id,
            )
        ).mappings().one_or_none()
        return _claim_record(row) if row is not None else None

    def list_claims(self, session_id: str) -> tuple[ClaimRecord, ...]:
        rows = self._connection.execute(
            sa.select(claims)
            .where(claims.c.session_id == session_id)
            .order_by(claims.c.claim_id)
        ).mappings()
        return tuple(_claim_record(row) for row in rows)

    def add_analysis(self, record: AnalysisRecord) -> None:
        validated = AnalysisRecord.model_validate(record.model_dump(mode="python"))
        self._insert(
            analysis,
            _analysis_values(validated),
            entity="analysis",
            record_id=validated.id,
        )

    def put_analysis(self, record: AnalysisRecord) -> bool:
        validated = AnalysisRecord.model_validate(record.model_dump(mode="python"))
        if validated.agent_task_id is None:
            raise RepositoryConflictError("analysis", validated.id)
        existing = self.get_analysis_by_task(validated.agent_task_id)
        if existing is not None:
            _assert_same("analysis", validated.id, existing, validated)
            return False
        inserted = self._insert_if_absent(
            analysis,
            _analysis_values(validated),
            conflict_columns=("agent_task_id",),
        )
        if not inserted:
            existing = self.get_analysis_by_task(validated.agent_task_id)
            if existing is None:
                raise RepositoryConflictError("analysis", validated.id)
            _assert_same("analysis", validated.id, existing, validated)
        return inserted

    def get_analysis_by_task(self, agent_task_id: str) -> AnalysisRecord | None:
        row = self._connection.execute(
            sa.select(analysis).where(analysis.c.agent_task_id == agent_task_id)
        ).mappings().one_or_none()
        return _analysis_record(row) if row is not None else None

    def list_analysis(self, session_id: str) -> tuple[AnalysisRecord, ...]:
        rows = self._connection.execute(
            sa.select(analysis)
            .where(analysis.c.session_id == session_id)
            .order_by(analysis.c.created_at, analysis.c.id)
        ).mappings()
        return tuple(_analysis_record(row) for row in rows)


class RepositoryUnitOfWork:
    """Repository collection bound to one caller-owned database transaction."""

    def __init__(self, connection: Connection) -> None:
        self.sessions = SessionRepository(connection)
        self.runs = CoordinatorRunRepository(connection)
        self.transitions = WorkflowTransitionRepository(connection)
        self.agent_tasks = AgentTaskRepository(connection)
        self.artifacts = ArtifactRepository(connection)


def _assert_immutable(
    entity: str,
    record_id: str,
    current: Any,
    replacement: Any,
    fields: tuple[str, ...],
) -> None:
    if any(getattr(current, field) != getattr(replacement, field) for field in fields):
        raise RepositoryConflictError(entity, record_id)


def _assert_same(entity: str, record_id: str, current: Any, replay: Any) -> None:
    if current.model_dump(mode="json") != replay.model_dump(mode="json"):
        raise RepositoryConflictError(entity, record_id)


def _assert_reusable_artifact(
    entity: str,
    record_id: str,
    current: EvidenceRecord | ClaimRecord,
    replay: EvidenceRecord | ClaimRecord,
) -> None:
    current_payload = current.evidence if isinstance(current, EvidenceRecord) else current.claim
    replay_payload = replay.evidence if isinstance(replay, EvidenceRecord) else replay.claim
    if (
        current.session_id != replay.session_id
        or current.artifact_schema_version != replay.artifact_schema_version
        or current_payload.model_dump(mode="json") != replay_payload.model_dump(mode="json")
    ):
        raise RepositoryConflictError(entity, record_id)


def _transition_id(record: WorkflowTransitionRecord) -> str:
    return f"{record.session_id}:{record.sequence}"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _session_record(row: RowMapping) -> SessionRecord:
    values = dict(row)
    values["created_at"] = _aware(values["created_at"])
    values["updated_at"] = _aware(values["updated_at"])
    return SessionRecord.model_validate(values)


def _run_record(row: RowMapping) -> CoordinatorRunRecord:
    values = dict(row)
    values["started_at"] = _aware(values["started_at"])
    if values["finished_at"] is not None:
        values["finished_at"] = _aware(values["finished_at"])
    return CoordinatorRunRecord.model_validate(values)


def _workflow_transition_record(row: RowMapping) -> WorkflowTransitionRecord:
    values = dict(row)
    values["occurred_at"] = _aware(values["occurred_at"])
    return WorkflowTransitionRecord.model_validate(values)


def _agent_task_record(row: RowMapping) -> AgentTaskRecord:
    values = dict(row)
    values["started_at"] = _aware(values["started_at"])
    if values["finished_at"] is not None:
        values["finished_at"] = _aware(values["finished_at"])
    return AgentTaskRecord.model_validate(values)


def _evidence_record(row: RowMapping) -> EvidenceRecord:
    return EvidenceRecord(
        id=row["id"],
        session_id=row["session_id"],
        agent_task_id=row["agent_task_id"],
        artifact_schema_version=row["artifact_schema_version"],
        evidence=Evidence(
            id=row["evidence_id"],
            title=row["title"],
            source_url=row["source_url"],
            source_type=row["source_type"],
            summary=row["summary"],
            relevance=row["relevance"],
            retrieved_at=_aware(row["retrieved_at"]),
        ),
    )


def _evidence_values(record: EvidenceRecord) -> dict[str, Any]:
    item = record.evidence
    return {
        "id": record.id,
        "session_id": record.session_id,
        "agent_task_id": record.agent_task_id,
        "evidence_id": item.id,
        "title": item.title,
        "source_url": str(item.source_url) if item.source_url is not None else None,
        "source_type": item.source_type,
        "summary": item.summary,
        "relevance": item.relevance,
        "retrieved_at": item.retrieved_at,
        "artifact_schema_version": record.artifact_schema_version,
    }


def _claim_record(row: RowMapping) -> ClaimRecord:
    return ClaimRecord(
        id=row["id"],
        session_id=row["session_id"],
        agent_task_id=row["agent_task_id"],
        artifact_schema_version=row["artifact_schema_version"],
        claim=Claim(
            id=row["claim_id"],
            statement=row["statement"],
            evidence_ids=row["evidence_ids"],
            confidence=row["confidence"],
            caveats=row["caveats"],
        ),
    )


def _claim_values(record: ClaimRecord) -> dict[str, Any]:
    item = record.claim
    return {
        "id": record.id,
        "session_id": record.session_id,
        "agent_task_id": record.agent_task_id,
        "claim_id": item.id,
        "statement": item.statement,
        "evidence_ids": item.evidence_ids,
        "confidence": item.confidence,
        "caveats": item.caveats,
        "artifact_schema_version": record.artifact_schema_version,
    }


def _research_artifact_record(row: RowMapping) -> ResearchArtifactRecord:
    return ResearchArtifactRecord(
        id=row["id"],
        session_id=row["session_id"],
        agent_task_id=row["agent_task_id"],
        envelope=ArtifactEnvelope[EvidenceBundle](
            schema_version=row["artifact_schema_version"],
            provenance=ArtifactProvenance(
                producer_agent=row["producer_agent"],
                remote_task_id=row["remote_task_id"],
                created_at=_aware(row["created_at"]),
            ),
            payload=EvidenceBundle.model_validate(row["payload"]),
        ),
    )


def _research_artifact_values(record: ResearchArtifactRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "agent_task_id": record.agent_task_id,
        "payload": record.envelope.payload.model_dump(mode="json"),
        "artifact_schema_version": record.envelope.schema_version,
        "producer_agent": record.envelope.provenance.producer_agent,
        "remote_task_id": record.envelope.provenance.remote_task_id,
        "created_at": record.envelope.provenance.created_at,
    }


def _recommendation_challenge_record(
    row: RowMapping,
) -> RecommendationChallengeRecord:
    return RecommendationChallengeRecord(
        id=row["id"],
        session_id=row["session_id"],
        agent_task_id=row["agent_task_id"],
        envelope=ArtifactEnvelope[RecommendationChallenge](
            schema_version=row["artifact_schema_version"],
            provenance=ArtifactProvenance(
                producer_agent=row["producer_agent"],
                remote_task_id=row["remote_task_id"],
                created_at=_aware(row["created_at"]),
            ),
            payload=RecommendationChallenge.model_validate(row["payload"]),
        ),
    )


def _recommendation_challenge_values(
    record: RecommendationChallengeRecord,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "agent_task_id": record.agent_task_id,
        "payload": record.envelope.payload.model_dump(mode="json"),
        "artifact_schema_version": record.envelope.schema_version,
        "producer_agent": record.envelope.provenance.producer_agent,
        "remote_task_id": record.envelope.provenance.remote_task_id,
        "created_at": record.envelope.provenance.created_at,
    }


def _verification_report_record(row: RowMapping) -> VerificationReportRecord:
    return VerificationReportRecord(
        id=row["id"],
        session_id=row["session_id"],
        agent_task_id=row["agent_task_id"],
        envelope=ArtifactEnvelope[VerificationReport](
            schema_version=row["artifact_schema_version"],
            provenance=ArtifactProvenance(
                producer_agent=row["producer_agent"],
                remote_task_id=row["remote_task_id"],
                created_at=_aware(row["created_at"]),
            ),
            payload=VerificationReport.model_validate(row["payload"]),
        ),
    )


def _verification_report_values(record: VerificationReportRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "agent_task_id": record.agent_task_id,
        "payload": record.envelope.payload.model_dump(mode="json"),
        "artifact_schema_version": record.envelope.schema_version,
        "producer_agent": record.envelope.provenance.producer_agent,
        "remote_task_id": record.envelope.provenance.remote_task_id,
        "created_at": record.envelope.provenance.created_at,
    }


def _analysis_record(row: RowMapping) -> AnalysisRecord:
    return AnalysisRecord(
        id=row["id"],
        session_id=row["session_id"],
        agent_task_id=row["agent_task_id"],
        analysis=DecisionAnalysis.model_validate(row["payload"]),
        artifact_schema_version=row["artifact_schema_version"],
        created_at=_aware(row["created_at"]),
    )


def _analysis_values(record: AnalysisRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "agent_task_id": record.agent_task_id,
        "recommendation": record.analysis.recommendation,
        "payload": record.analysis.model_dump(mode="json"),
        "artifact_schema_version": record.artifact_schema_version,
        "created_at": record.created_at,
    }
