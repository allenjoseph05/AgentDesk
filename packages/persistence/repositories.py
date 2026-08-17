"""SQLAlchemy repository implementations for durable AgentDesk records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError

from packages.contracts import Claim, DecisionAnalysis, Evidence
from packages.persistence.records import (
    AgentTaskRecord,
    AnalysisRecord,
    ClaimRecord,
    CoordinatorRunRecord,
    EvidenceRecord,
    SessionRecord,
)
from packages.persistence.schema import (
    agent_tasks,
    analysis,
    claims,
    coordinator_runs,
    evidence,
    sessions,
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
    def add_evidence(self, record: EvidenceRecord) -> None:
        validated = EvidenceRecord.model_validate(record.model_dump(mode="python"))
        item = validated.evidence
        values = {
            "id": validated.id,
            "session_id": validated.session_id,
            "agent_task_id": validated.agent_task_id,
            "evidence_id": item.id,
            "title": item.title,
            "source_url": str(item.source_url) if item.source_url is not None else None,
            "source_type": item.source_type,
            "summary": item.summary,
            "relevance": item.relevance,
            "retrieved_at": item.retrieved_at,
            "artifact_schema_version": validated.artifact_schema_version,
        }
        self._insert(
            evidence,
            values,
            entity="evidence",
            record_id=validated.id,
        )

    def list_evidence(self, session_id: str) -> tuple[EvidenceRecord, ...]:
        rows = self._connection.execute(
            sa.select(evidence)
            .where(evidence.c.session_id == session_id)
            .order_by(evidence.c.retrieved_at, evidence.c.evidence_id)
        ).mappings()
        return tuple(_evidence_record(row) for row in rows)

    def add_claim(self, record: ClaimRecord) -> None:
        validated = ClaimRecord.model_validate(record.model_dump(mode="python"))
        item = validated.claim
        values = {
            "id": validated.id,
            "session_id": validated.session_id,
            "agent_task_id": validated.agent_task_id,
            "claim_id": item.id,
            "statement": item.statement,
            "evidence_ids": item.evidence_ids,
            "confidence": item.confidence,
            "caveats": item.caveats,
            "artifact_schema_version": validated.artifact_schema_version,
        }
        self._insert(
            claims,
            values,
            entity="claim",
            record_id=validated.id,
        )

    def list_claims(self, session_id: str) -> tuple[ClaimRecord, ...]:
        rows = self._connection.execute(
            sa.select(claims)
            .where(claims.c.session_id == session_id)
            .order_by(claims.c.claim_id)
        ).mappings()
        return tuple(_claim_record(row) for row in rows)

    def add_analysis(self, record: AnalysisRecord) -> None:
        validated = AnalysisRecord.model_validate(record.model_dump(mode="python"))
        values = {
            "id": validated.id,
            "session_id": validated.session_id,
            "agent_task_id": validated.agent_task_id,
            "recommendation": validated.analysis.recommendation,
            "payload": validated.analysis.model_dump(mode="json"),
            "artifact_schema_version": validated.artifact_schema_version,
            "created_at": validated.created_at,
        }
        self._insert(
            analysis,
            values,
            entity="analysis",
            record_id=validated.id,
        )

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


def _analysis_record(row: RowMapping) -> AnalysisRecord:
    return AnalysisRecord(
        id=row["id"],
        session_id=row["session_id"],
        agent_task_id=row["agent_task_id"],
        analysis=DecisionAnalysis.model_validate(row["payload"]),
        artifact_schema_version=row["artifact_schema_version"],
        created_at=_aware(row["created_at"]),
    )
