"""Transaction-scoped persistence repository tests."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from packages.contracts import DOMAIN_SCHEMA_VERSION
from packages.persistence import (
    AgentTaskRecord,
    AnalysisRecord,
    ClaimRecord,
    CoordinatorRunRecord,
    Database,
    EvidenceRecord,
    RecordNotFoundError,
    RepositoryConflictError,
    SessionRecord,
    metadata,
)
from packages.testing import load_research_fixture

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def database() -> Database:
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


def _session() -> SessionRecord:
    return SessionRecord(
        id="session-1",
        ag_ui_thread_id="thread-1",
        last_run_id="run-1",
        last_action_id="action-1",
        question="Should we use PostgreSQL or MongoDB?",
        status="planning",
        active_step="plan",
        created_at=NOW,
        updated_at=NOW,
    )


def _run(*, run_id: str = "run-1", action_id: str = "action-1") -> CoordinatorRunRecord:
    return CoordinatorRunRecord(
        run_id=run_id,
        session_id="session-1",
        ag_ui_thread_id="thread-1",
        action_id=action_id,
        action_type="start_research",
        status="accepted",
        started_at=NOW,
    )


def _task() -> AgentTaskRecord:
    return AgentTaskRecord(
        id="task-row-1",
        session_id="session-1",
        run_id="run-1",
        agent_id="researcher",
        skill="web-research",
        status="pending",
        started_at=NOW,
    )


def test_unit_of_work_commits_typed_session_run_and_task_records(
    database: Database,
) -> None:
    with database.transaction() as repositories:
        repositories.sessions.add(_session())
        repositories.runs.add(_run())
        repositories.agent_tasks.add(_task())

    completed_at = datetime(2026, 8, 17, 12, 5, tzinfo=UTC)
    with database.transaction() as repositories:
        session = repositories.sessions.require("session-1")
        repositories.sessions.replace(
            session.model_copy(
                update={
                    "status": "researching",
                    "active_step": "research",
                    "updated_at": completed_at,
                }
            )
        )
        task = repositories.agent_tasks.get("task-row-1")
        assert task is not None
        repositories.agent_tasks.replace(
            task.model_copy(
                update={
                    "a2a_context_id": "context-42",
                    "remote_task_id": "remote-task-42",
                    "status": "working",
                }
            )
        )
        run = repositories.runs.get_by_action("action-1")

        assert run is not None
        assert run.run_id == "run-1"
        assert repositories.sessions.require("session-1").status == "researching"
        remote = repositories.agent_tasks.get_by_remote(
            agent_id="researcher",
            remote_task_id="remote-task-42",
        )
        assert remote is not None
        assert remote.a2a_context_id == "context-42"


def test_caller_owned_transaction_rollback_isolates_test_data(database: Database) -> None:
    with database.engine.connect() as connection:
        transaction = connection.begin()
        repositories = database.repositories(connection)
        repositories.sessions.add(_session())
        assert repositories.sessions.get("session-1") is not None
        transaction.rollback()

    with database.transaction() as repositories:
        assert repositories.sessions.get("session-1") is None


def test_unit_of_work_rolls_back_every_write_when_body_fails(database: Database) -> None:
    with pytest.raises(RuntimeError, match="abort transaction"):
        with database.transaction() as repositories:
            repositories.sessions.add(_session())
            repositories.runs.add(_run())
            raise RuntimeError("abort transaction")

    with database.transaction() as repositories:
        assert repositories.sessions.get("session-1") is None
        assert repositories.runs.get("run-1") is None


def test_database_constraints_are_translated_to_repository_conflicts(
    database: Database,
) -> None:
    with database.transaction() as repositories:
        repositories.sessions.add(_session())
        repositories.runs.add(_run())

    with pytest.raises(RepositoryConflictError) as error:
        with database.transaction() as repositories:
            repositories.runs.add(_run(run_id="run-2", action_id="action-1"))

    assert error.value.entity == "coordinator run"
    with database.transaction() as repositories:
        assert repositories.runs.get_by_action("action-1") == _run()


def test_replace_rejects_missing_records(database: Database) -> None:
    with pytest.raises(RecordNotFoundError, match="missing-session"):
        with database.transaction() as repositories:
            repositories.sessions.replace(
                _session().model_copy(update={"id": "missing-session"})
            )


def test_replace_rejects_changes_to_correlation_identity(database: Database) -> None:
    with database.transaction() as repositories:
        repositories.sessions.add(_session())
        repositories.runs.add(_run())

    with pytest.raises(RepositoryConflictError):
        with database.transaction() as repositories:
            run = repositories.runs.get("run-1")
            assert run is not None
            repositories.runs.replace(
                run.model_copy(update={"action_id": "different-action"})
            )

    with database.transaction() as repositories:
        assert repositories.runs.get("run-1") == _run()


def test_artifact_repository_round_trips_typed_domain_models(database: Database) -> None:
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    assert fixture.decision_analysis is not None

    with database.transaction() as repositories:
        repositories.sessions.add(_session())
        repositories.runs.add(_run())
        repositories.agent_tasks.add(_task())
        for item in fixture.evidence_bundle.evidence:
            repositories.artifacts.add_evidence(
                EvidenceRecord(
                    id=f"row-{item.id}",
                    session_id="session-1",
                    agent_task_id="task-row-1",
                    evidence=item,
                    artifact_schema_version=DOMAIN_SCHEMA_VERSION,
                )
            )
        for item in fixture.evidence_bundle.claims:
            repositories.artifacts.add_claim(
                ClaimRecord(
                    id=f"row-{item.id}",
                    session_id="session-1",
                    agent_task_id="task-row-1",
                    claim=item,
                    artifact_schema_version=DOMAIN_SCHEMA_VERSION,
                )
            )
        repositories.artifacts.add_analysis(
            AnalysisRecord(
                id="analysis-row-1",
                session_id="session-1",
                analysis=fixture.decision_analysis,
                artifact_schema_version=DOMAIN_SCHEMA_VERSION,
                created_at=NOW,
            )
        )

    with database.transaction() as repositories:
        persisted_evidence = tuple(
            record.evidence for record in repositories.artifacts.list_evidence("session-1")
        )
        persisted_claims = tuple(
            record.claim for record in repositories.artifacts.list_claims("session-1")
        )
        persisted_analysis = repositories.artifacts.list_analysis("session-1")

    assert {item.id: item for item in persisted_evidence} == {
        item.id: item for item in fixture.evidence_bundle.evidence
    }
    assert {item.id: item for item in persisted_claims} == {
        item.id: item for item in fixture.evidence_bundle.claims
    }
    assert len(persisted_analysis) == 1
    assert persisted_analysis[0].analysis == fixture.decision_analysis


def test_coordinator_business_logic_does_not_import_sqlalchemy() -> None:
    for module_path in (ROOT / "agents" / "coordinator").glob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(name == "sqlalchemy" or name.startswith("sqlalchemy.") for name in imports)
