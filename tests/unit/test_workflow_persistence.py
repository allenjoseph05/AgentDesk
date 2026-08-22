"""Durable Coordinator state, correlation, and artifact commit-point tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from agents.coordinator.persistence import (
    ArtifactProvenanceError,
    WorkflowPersistenceService,
)
from agents.coordinator.workflow_state import WorkflowStateMachine
from packages.contracts import ArtifactEnvelope, ArtifactProvenance
from packages.persistence import (
    AgentTaskRecord,
    Database,
    RepositoryConflictError,
    metadata,
)
from packages.testing import load_research_fixture


class AdvancingClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


@pytest.fixture
def database() -> Iterator[Database]:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    database = Database(engine)
    try:
        yield database
    finally:
        database.dispose()


def _initialized_service(
    database: Database,
) -> tuple[WorkflowPersistenceService, WorkflowStateMachine]:
    service = WorkflowPersistenceService(database)
    machine = WorkflowStateMachine(
        "session-1",
        clock=AdvancingClock(),
        on_transition=service.persist_transition,
    )
    service.initialize(
        snapshot=machine.snapshot,
        ag_ui_thread_id="thread-1",
        run_id="run-1",
        action_id="action-1",
        action_type="start_research",
        question="Should we use PostgreSQL or MongoDB?",
    )
    return service, machine


def _task(
    agent_id: str,
    task_id: str,
    *,
    skill: str,
    started_at: datetime,
) -> AgentTaskRecord:
    return AgentTaskRecord(
        id=task_id,
        session_id="session-1",
        run_id="run-1",
        agent_id=agent_id,
        skill=skill,
        started_at=started_at,
    )


def test_state_machine_transitions_are_committed_in_order(database: Database) -> None:
    _, machine = _initialized_service(database)

    machine.transition("planning", active_step="plan")
    machine.transition("researching", active_step="research", completed_steps=["plan"])
    machine.transition(
        "analyzing",
        active_step="analysis",
        completed_steps=["research"],
    )
    machine.transition("completed", completed_steps=["analysis"])

    with database.transaction() as repositories:
        session = repositories.sessions.require("session-1")
        history = repositories.transitions.list_by_session("session-1")

    assert session.status == "completed"
    assert session.completed_steps == ["plan", "research", "analysis"]
    assert [item.sequence for item in history] == [1, 2, 3, 4]
    assert [(item.from_status, item.to_status) for item in history] == [
        ("created", "planning"),
        ("planning", "researching"),
        ("researching", "analyzing"),
        ("analyzing", "completed"),
    ]


def test_remote_a2a_identity_is_durable_and_cannot_be_rebound(
    database: Database,
) -> None:
    service, machine = _initialized_service(database)
    service.create_agent_task(
        _task(
            "researcher",
            "research-task",
            skill="web-research",
            started_at=machine.snapshot.updated_at,
        )
    )

    assert service.register_remote_task(
        "research-task",
        remote_task_id="remote-42",
        a2a_context_id="context-42",
    )
    assert not WorkflowPersistenceService(database).register_remote_task(
        "research-task",
        remote_task_id="remote-42",
        a2a_context_id="context-42",
    )

    with pytest.raises(RepositoryConflictError):
        service.register_remote_task(
            "research-task",
            remote_task_id="remote-other",
            a2a_context_id="context-42",
        )

    with database.transaction() as repositories:
        task = repositories.agent_tasks.require("research-task")
    assert task.remote_task_id == "remote-42"
    assert task.a2a_context_id == "context-42"
    assert task.status == "submitted"


def test_remote_a2a_context_can_enrich_an_existing_task_identity(
    database: Database,
) -> None:
    service, machine = _initialized_service(database)
    service.create_agent_task(
        _task(
            "researcher",
            "research-task",
            skill="web-research",
            started_at=machine.snapshot.updated_at,
        )
    )

    assert service.register_remote_task(
        "research-task",
        remote_task_id="remote-42",
    )
    assert service.register_remote_task(
        "research-task",
        remote_task_id="remote-42",
        a2a_context_id="context-42",
    )
    assert not service.register_remote_task(
        "research-task",
        remote_task_id="remote-42",
    )
    assert not service.register_remote_task(
        "research-task",
        remote_task_id="remote-42",
        a2a_context_id="context-42",
    )
    with pytest.raises(RepositoryConflictError):
        service.register_remote_task(
            "research-task",
            remote_task_id="remote-42",
            a2a_context_id="different-context",
        )

    with database.transaction() as repositories:
        task = repositories.agent_tasks.require("research-task")
    assert task.a2a_context_id == "context-42"


def test_agent_task_terminal_outcome_is_durable_and_idempotent(
    database: Database,
) -> None:
    service, machine = _initialized_service(database)
    service.create_agent_task(
        _task(
            "researcher",
            "research-task",
            skill="web-research",
            started_at=machine.snapshot.updated_at,
        )
    )
    finished_at = machine.snapshot.updated_at + timedelta(seconds=1)

    assert service.finish_agent_task(
        "research-task",
        status="completed",
        finished_at=finished_at,
    )
    assert not service.finish_agent_task(
        "research-task",
        status="completed",
        finished_at=finished_at,
    )
    with pytest.raises(RepositoryConflictError):
        service.finish_agent_task(
            "research-task",
            status="cancelled",
            finished_at=finished_at,
        )

    with database.transaction() as repositories:
        task = repositories.agent_tasks.require("research-task")
    assert task.status == "completed"
    assert task.finished_at == finished_at


def test_cancelled_tasks_accept_late_correlation_without_resurrection(
    database: Database,
) -> None:
    service, machine = _initialized_service(database)
    for agent_id, task_id, skill in (
        ("researcher", "research-task", "web-research"),
        ("analyst", "analysis-task", "decision-analysis"),
    ):
        service.create_agent_task(
            _task(
                agent_id,
                task_id,
                skill=skill,
                started_at=machine.snapshot.updated_at,
            )
        )
    finished_at = machine.snapshot.updated_at + timedelta(seconds=1)

    assert service.cancel_run_agent_tasks(
        session_id="session-1",
        run_id="run-1",
        finished_at=finished_at,
    ) == ("analysis-task", "research-task")
    assert service.register_remote_task(
        "analysis-task",
        remote_task_id="late-analysis-task",
    )

    with database.transaction() as repositories:
        tasks = repositories.agent_tasks.list_by_session("session-1")
    assert [(task.id, task.status) for task in tasks] == [
        ("analysis-task", "cancelled"),
        ("research-task", "cancelled"),
    ]
    assert tasks[0].remote_task_id == "late-analysis-task"
    assert all(task.finished_at == finished_at for task in tasks)


def test_evidence_and_analysis_replay_is_exactly_once(database: Database) -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    assert fixture.decision_analysis is not None
    service, machine = _initialized_service(database)
    service.create_agent_task(
        _task(
            "researcher",
            "research-task",
            skill="web-research",
            started_at=machine.snapshot.updated_at,
        )
    )
    service.create_agent_task(
        _task(
            "analyst",
            "analysis-task",
            skill="decision-analysis",
            started_at=machine.snapshot.updated_at,
        )
    )
    service.register_remote_task("research-task", remote_task_id="remote-research")
    service.register_remote_task("analysis-task", remote_task_id="remote-analysis")
    evidence_envelope = ArtifactEnvelope(
        provenance=ArtifactProvenance(
            producer_agent="researcher",
            remote_task_id="remote-research",
            created_at=machine.snapshot.updated_at,
        ),
        payload=fixture.evidence_bundle,
    )
    analysis_envelope = ArtifactEnvelope(
        provenance=ArtifactProvenance(
            producer_agent="analyst",
            remote_task_id="remote-analysis",
            created_at=machine.snapshot.updated_at,
        ),
        payload=fixture.decision_analysis,
    )

    first = service.persist_evidence("session-1", "research-task", evidence_envelope)
    replay = service.persist_evidence("session-1", "research-task", evidence_envelope)
    assert first.evidence_inserted == len(fixture.evidence_bundle.evidence)
    assert first.claims_inserted == len(fixture.evidence_bundle.claims)
    assert first.bundle_inserted
    assert replay.evidence_inserted == 0
    assert replay.claims_inserted == 0
    assert not replay.bundle_inserted
    assert service.persist_analysis("session-1", "analysis-task", analysis_envelope)
    assert not service.persist_analysis("session-1", "analysis-task", analysis_envelope)

    changed_bundle = fixture.evidence_bundle.model_copy(deep=True)
    changed_bundle.evidence[0].summary = "Conflicting replay content."
    conflicting_envelope = evidence_envelope.model_copy(
        update={"payload": changed_bundle}
    )
    with pytest.raises(RepositoryConflictError):
        service.persist_evidence("session-1", "research-task", conflicting_envelope)

    with database.transaction() as repositories:
        evidence = repositories.artifacts.list_evidence("session-1")
        claims = repositories.artifacts.list_claims("session-1")
        analyses = repositories.artifacts.list_analysis("session-1")
        research_artifact = repositories.artifacts.get_research_artifact_by_task(
            "research-task"
        )
    assert len(evidence) == len(fixture.evidence_bundle.evidence)
    assert len(claims) == len(fixture.evidence_bundle.claims)
    assert len(analyses) == 1
    assert research_artifact is not None
    assert research_artifact.envelope == evidence_envelope
    assert evidence[0].evidence.summary != "Conflicting replay content."


def test_bundle_level_research_context_is_durable(database: Database) -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    service, machine = _initialized_service(database)
    service.create_agent_task(
        _task(
            "researcher",
            "research-task",
            skill="web-research",
            started_at=machine.snapshot.updated_at,
        )
    )
    service.register_remote_task("research-task", remote_task_id="remote-research")
    envelope = ArtifactEnvelope(
        provenance=ArtifactProvenance(
            producer_agent="researcher",
            remote_task_id="remote-research",
            created_at=machine.snapshot.updated_at,
        ),
        payload=fixture.evidence_bundle,
    )

    service.persist_evidence("session-1", "research-task", envelope)

    with database.transaction() as repositories:
        stored = repositories.artifacts.get_research_artifact_by_task("research-task")
    assert stored is not None
    assert stored.envelope.payload.unknowns == fixture.evidence_bundle.unknowns
    assert stored.envelope.payload.research_notes == fixture.evidence_bundle.research_notes
    assert stored.envelope.provenance == envelope.provenance


def test_verification_report_replay_is_exactly_once(database: Database) -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    assert fixture.verification_report is not None
    service, machine = _initialized_service(database)
    service.create_agent_task(
        _task(
            "researcher",
            "research-task",
            skill="web-research",
            started_at=machine.snapshot.updated_at,
        )
    )
    service.register_remote_task("research-task", remote_task_id="remote-research")
    service.persist_evidence(
        "session-1",
        "research-task",
        ArtifactEnvelope(
            provenance=ArtifactProvenance(
                producer_agent="researcher",
                remote_task_id="remote-research",
                created_at=machine.snapshot.updated_at,
            ),
            payload=fixture.evidence_bundle,
        ),
    )
    service.create_agent_task(
        _task(
            "verifier",
            "verification-task",
            skill="fact-verification",
            started_at=machine.snapshot.updated_at,
        )
    )
    service.register_remote_task(
        "verification-task",
        remote_task_id="remote-verification",
    )
    envelope = ArtifactEnvelope(
        provenance=ArtifactProvenance(
            producer_agent="verifier",
            remote_task_id="remote-verification",
            created_at=machine.snapshot.updated_at,
        ),
        payload=fixture.verification_report,
    )

    assert service.persist_verification_report(
        "session-1", "verification-task", envelope
    )
    assert not service.persist_verification_report(
        "session-1", "verification-task", envelope
    )

    conflicting_report = fixture.verification_report.model_copy(deep=True)
    conflicting_report.results[0].rationale = "Conflicting replay rationale."
    with pytest.raises(RepositoryConflictError):
        service.persist_verification_report(
            "session-1",
            "verification-task",
            envelope.model_copy(update={"payload": conflicting_report}),
        )

    with database.transaction() as repositories:
        stored = repositories.artifacts.list_verification_reports("session-1")
    assert len(stored) == 1
    assert stored[0].envelope == envelope


def test_artifact_provenance_must_match_durable_task(database: Database) -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    service, machine = _initialized_service(database)
    service.create_agent_task(
        _task(
            "researcher",
            "research-task",
            skill="web-research",
            started_at=machine.snapshot.updated_at,
        )
    )
    service.register_remote_task("research-task", remote_task_id="remote-research")
    envelope = ArtifactEnvelope(
        provenance=ArtifactProvenance(
            producer_agent="researcher",
            remote_task_id="different-remote-task",
            created_at=machine.snapshot.updated_at,
        ),
        payload=fixture.evidence_bundle,
    )

    with pytest.raises(ArtifactProvenanceError, match="remote task identity"):
        service.persist_evidence("session-1", "research-task", envelope)

    with database.transaction() as repositories:
        assert repositories.artifacts.list_evidence("session-1") == ()
