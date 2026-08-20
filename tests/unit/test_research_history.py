"""Persistence-backed research history and no-rerun rehydration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import StaticPool

from agents.coordinator.main import create_app
from agents.coordinator.persistence import WorkflowPersistenceService
from agents.coordinator.projection import DurableAgUiProjector
from agents.coordinator.run_adapter import CoordinatorCommand, CoordinatorRunUpdate
from agents.coordinator.workflow_state import WorkflowStateMachine
from packages.contracts import ArtifactEnvelope, ArtifactProvenance
from packages.persistence import AgentTaskRecord, Database, metadata
from packages.testing import load_research_fixture

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


class ExplodingExecutor:
    """Fails if a history read accidentally enters the command execution path."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        command: CoordinatorCommand,
    ) -> AsyncIterator[CoordinatorRunUpdate]:
        self.calls += 1
        raise AssertionError(f"History read reran Coordinator command: {command}")
        if False:  # pragma: no cover - makes this an async generator
            yield


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


def _seed_completed_session(database: Database) -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    assert fixture.decision_analysis is not None
    moments = iter(NOW + timedelta(seconds=index) for index in range(20))
    persistence = WorkflowPersistenceService(database)
    machine = WorkflowStateMachine(
        "session-history",
        clock=lambda: next(moments),
        on_transition=persistence.persist_transition,
    )
    persistence.initialize(
        snapshot=machine.snapshot,
        ag_ui_thread_id="thread-history",
        run_id="run-history",
        action_id="action-history",
        action_type="start_research",
        question="Should we use PostgreSQL or MongoDB?",
    )
    for task_id, agent_id, skill, remote_task_id in (
        ("research-task", "researcher", "web-research", "remote-research"),
        ("analysis-task", "analyst", "decision-analysis", "remote-analysis"),
    ):
        persistence.create_agent_task(
            AgentTaskRecord(
                id=task_id,
                session_id="session-history",
                run_id="run-history",
                agent_id=agent_id,
                skill=skill,
                started_at=machine.snapshot.updated_at,
            )
        )
        persistence.register_remote_task(
            task_id,
            remote_task_id=remote_task_id,
            a2a_context_id="context-history",
        )

    persistence.persist_evidence(
        "session-history",
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
    persistence.persist_analysis(
        "session-history",
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
    finished_at = machine.snapshot.updated_at + timedelta(seconds=1)
    persistence.finish_agent_task(
        "research-task",
        status="completed",
        finished_at=finished_at,
    )
    persistence.finish_agent_task(
        "analysis-task",
        status="completed",
        finished_at=finished_at,
    )
    machine.transition("planning", active_step="plan")
    machine.transition("researching", active_step="research")
    machine.transition("analyzing", active_step="analysis")
    machine.transition("completed")


def _seed_active_session(database: Database) -> None:
    persistence = WorkflowPersistenceService(database)
    machine = WorkflowStateMachine("session-active", clock=lambda: NOW + timedelta(hours=1))
    persistence.initialize(
        snapshot=machine.snapshot,
        ag_ui_thread_id="thread-active",
        run_id="run-active",
        action_id="action-active",
        action_type="start_research",
        question="What is still running?",
    )


async def _get_json(app: Any, path: str) -> tuple[int, dict[str, Any]]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code, response.json()


def test_web_can_list_prior_sessions_in_recent_order(database: Database) -> None:
    _seed_completed_session(database)
    _seed_active_session(database)
    executor = ExplodingExecutor()
    app = create_app(database=database, command_executor=executor)

    status_code, body = asyncio.run(_get_json(app, "/api/sessions?limit=10"))

    assert status_code == 200
    assert [item["sessionId"] for item in body["sessions"]] == [
        "session-active",
        "session-history",
    ]
    assert body["sessions"][1] == {
        "sessionId": "session-history",
        "threadId": "thread-history",
        "question": "Should we use PostgreSQL or MongoDB?",
        "status": "completed",
        "lastRunId": "run-history",
        "createdAt": "2026-08-20T12:00:00Z",
        "updatedAt": "2026-08-20T12:00:04Z",
    }
    assert executor.calls == 0


def test_completed_detail_rehydrates_exact_ag_ui_state_without_rerun(
    database: Database,
) -> None:
    _seed_completed_session(database)
    executor = ExplodingExecutor()
    app = create_app(database=database, command_executor=executor)
    expected = DurableAgUiProjector(database).snapshot("session-history").to_ag_ui()

    status_code, body = asyncio.run(
        _get_json(app, "/api/sessions/session-history")
    )

    assert status_code == 200
    assert body["state"] == expected
    assert body["state"]["status"] == "completed"
    assert body["state"]["analysis"] is not None
    assert body["state"]["evidenceCount"] > 0
    assert any(message.startswith("Evidence gap:") for message in body["state"]["warnings"])
    assert executor.calls == 0


def test_history_filters_by_thread_and_rejects_unfinished_or_missing_detail(
    database: Database,
) -> None:
    _seed_completed_session(database)
    _seed_active_session(database)
    app = create_app(database=database, command_executor=ExplodingExecutor())

    filtered_status, filtered = asyncio.run(
        _get_json(app, "/api/sessions?threadId=thread-history")
    )
    active_status, active = asyncio.run(
        _get_json(app, "/api/sessions/session-active")
    )
    missing_status, missing = asyncio.run(
        _get_json(app, "/api/sessions/session-missing")
    )

    assert filtered_status == 200
    assert [item["sessionId"] for item in filtered["sessions"]] == ["session-history"]
    assert (active_status, active) == (
        409,
        {"detail": "Session has not reached a terminal state."},
    )
    assert (missing_status, missing) == (404, {"detail": "Session was not found."})
