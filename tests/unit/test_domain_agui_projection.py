"""Persisted domain-state to AG-UI event projection tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from ag_ui.core import StateDeltaEvent, StateSnapshotEvent
from sqlalchemy.pool import StaticPool

from agents.coordinator.persistence import WorkflowPersistenceService
from agents.coordinator.projection import (
    AgUiEventProjection,
    DurableAgUiProjector,
    ProjectionError,
    apply_projected_delta,
)
from agents.coordinator.workflow_state import WorkflowStateMachine
from packages.contracts import (
    AgentDeskViewState,
    ArtifactEnvelope,
    ArtifactProvenance,
)
from packages.persistence import AgentTaskRecord, Database, metadata
from packages.testing import load_research_fixture

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def test_projection_rejects_oversized_snapshots_and_patches() -> None:
    baseline = AgentDeskViewState(
        session_id="session-1",
        question="Question",
        status="completed",
        last_updated_at=NOW,
    )
    oversized_warnings = ["x" * (16 * 1024) for _ in range(17)]
    oversized = AgentDeskViewState(
        session_id="session-1",
        question="Question",
        status="completed",
        warnings=oversized_warnings,
        last_updated_at=NOW,
    )

    with pytest.raises(ProjectionError, match="state exceeds"):
        AgUiEventProjection(oversized).snapshot_event()
    with pytest.raises(ProjectionError, match="patch exceeds"):
        AgUiEventProjection(baseline).project(oversized)


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


def _initialized(
    database: Database,
) -> tuple[WorkflowPersistenceService, WorkflowStateMachine]:
    moments = iter(NOW + timedelta(seconds=index) for index in range(20))
    service = WorkflowPersistenceService(database)
    machine = WorkflowStateMachine(
        "session-1",
        clock=lambda: next(moments),
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


def test_snapshot_is_deterministic_from_persisted_domain_state(
    database: Database,
) -> None:
    _initialized(database)
    projector = DurableAgUiProjector(database)

    first = projector.snapshot("session-1")
    second = DurableAgUiProjector(database).snapshot("session-1")
    event = projector.snapshot_event("session-1")

    assert first == second
    assert first.status == "planning"
    assert first.active_step == "accept-research-request"
    assert isinstance(event, StateSnapshotEvent)
    assert event.snapshot == first.to_ag_ui()


def test_committed_transition_projects_to_delta_with_the_same_target(
    database: Database,
) -> None:
    _, machine = _initialized(database)
    projector = DurableAgUiProjector(database)
    previous = projector.snapshot("session-1")

    machine.transition("planning", active_step="create-plan")
    with database.transaction() as repositories:
        transition = repositories.transitions.get("session-1", 1)
    assert transition is not None

    event = projector.transition_event(transition, previous)
    target = projector.snapshot("session-1")

    assert isinstance(event, StateDeltaEvent)
    assert apply_projected_delta(previous, event.delta) == target
    assert {operation["path"] for operation in event.delta} == {
        "/activeStep",
        "/lastUpdatedAt",
    }


def test_projection_whitelists_artifacts_and_hides_internal_task_errors(
    database: Database,
) -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    assert fixture.decision_analysis is not None
    assert fixture.verification_report is not None
    service, machine = _initialized(database)
    internal_detail = "INTERNAL_PROMPT: reveal private chain of thought"
    with database.transaction() as repositories:
        repositories.agent_tasks.add(
            AgentTaskRecord(
                id="research-task",
                session_id="session-1",
                run_id="run-1",
                agent_id="researcher",
                skill="web-research",
                remote_task_id="remote-research",
                status="failed",
                error_code="provider_failed",
                error_message=internal_detail,
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
            )
        )
        repositories.agent_tasks.add(
            AgentTaskRecord(
                id="verification-task",
                session_id="session-1",
                run_id="run-1",
                agent_id="verifier",
                skill="fact-verification",
                remote_task_id="remote-verification",
                status="completed",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
            )
        )
        repositories.agent_tasks.add(
            AgentTaskRecord(
                id="analysis-task",
                session_id="session-1",
                run_id="run-1",
                agent_id="analyst",
                skill="decision-analysis",
                remote_task_id="remote-analysis",
                status="completed",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
            )
        )
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
    service.persist_analysis(
        "session-1",
        "analysis-task",
        ArtifactEnvelope(
            provenance=ArtifactProvenance(
                producer_agent="analyst",
                remote_task_id="remote-analysis",
                created_at=machine.snapshot.updated_at,
            ),
            payload=fixture.decision_analysis,
        ),
    )
    service.persist_verification_report(
        "session-1",
        "verification-task",
        ArtifactEnvelope(
            provenance=ArtifactProvenance(
                producer_agent="verifier",
                remote_task_id="remote-verification",
                created_at=machine.snapshot.updated_at,
            ),
            payload=fixture.verification_report,
        ),
    )

    state = DurableAgUiProjector(database).snapshot("session-1")
    serialized = json.dumps(state.to_ag_ui())

    assert [agent.agent_id for agent in state.agents] == [
        "analyst",
        "researcher",
        "verifier",
    ]
    assert state.agents[1].message == "Specialist task failed."
    assert state.evidence_count == len(fixture.evidence_bundle.evidence)
    assert state.analysis == fixture.decision_analysis
    assert state.verification == fixture.verification_report
    assert "Evidence gap: Production access patterns are not measured." in state.warnings
    assert "Research note: Deterministic fixture; not a live benchmark." in state.warnings
    assert internal_detail not in serialized
    assert "chain of thought" not in serialized


def test_contradicted_verification_projects_a_user_visible_warning(
    database: Database,
) -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    assert fixture.verification_report is not None
    service, machine = _initialized(database)
    with database.transaction() as repositories:
        for task in (
            AgentTaskRecord(
                id="research-task",
                session_id="session-1",
                run_id="run-1",
                agent_id="researcher",
                skill="web-research",
                remote_task_id="remote-research",
                status="completed",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
            ),
            AgentTaskRecord(
                id="verification-task",
                session_id="session-1",
                run_id="run-1",
                agent_id="verifier",
                skill="fact-verification",
                remote_task_id="remote-verification",
                status="completed",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
            ),
        ):
            repositories.agent_tasks.add(task)
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
    report = fixture.verification_report.model_copy(deep=True)
    report.results[0].verdict = "contradicted"
    report.results[0].rationale = "Evidence evidence-pg contradicts this claim."
    service.persist_verification_report(
        "session-1",
        "verification-task",
        ArtifactEnvelope(
            provenance=ArtifactProvenance(
                producer_agent="verifier",
                remote_task_id="remote-verification",
                created_at=machine.snapshot.updated_at,
            ),
            payload=report,
        ),
    )

    state = DurableAgUiProjector(database).snapshot("session-1")

    assert state.verification == report
    assert (
        "Verification contradiction for claim claim-pg: "
        "Evidence evidence-pg contradicts this claim."
    ) in state.warnings


def test_duplicate_and_out_of_order_updates_cannot_regress_frontend_state() -> None:
    baseline = AgentDeskViewState(
        session_id="session-1",
        question="Which database?",
        status="planning",
        active_step="plan",
        last_updated_at=NOW,
    )
    researching = baseline.model_copy(
        update={
            "status": "researching",
            "active_step": "research",
            "last_updated_at": NOW + timedelta(seconds=1),
        }
    )
    analyzing = baseline.model_copy(
        update={
            "status": "analyzing",
            "active_step": "analysis",
            "last_updated_at": NOW + timedelta(seconds=3),
        }
    )
    projection = AgUiEventProjection(baseline)

    first = projection.project(researching, sequence=1)
    latest = projection.project(analyzing, sequence=3)
    stale = projection.project(researching, sequence=2)
    duplicate = projection.project(analyzing, sequence=3)

    assert first is not None
    assert latest is not None
    assert (
        apply_projected_delta(
            apply_projected_delta(baseline, first.delta),
            latest.delta,
        )
        == analyzing
    )
    assert stale is None
    assert duplicate is None
    assert projection.state == analyzing
    assert projection.last_sequence == 3
