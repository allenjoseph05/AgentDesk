"""Initial persistence schema and Alembic reproducibility tests."""

from __future__ import annotations

import io
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from packages.persistence import metadata

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_ROOT = ROOT / ".test-databases"
EXPECTED_TABLES = {
    "sessions",
    "workflow_transitions",
    "coordinator_runs",
    "agent_tasks",
    "evidence",
    "claims",
    "research_artifacts",
    "analysis",
    "recommendation_challenges",
    "verification_reports",
}


def _config(database_path: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return config


@contextmanager
def _database_paths(*labels: str) -> Iterator[tuple[Path, ...]]:
    TEST_DATABASE_ROOT.mkdir(exist_ok=True)
    paths = tuple(
        TEST_DATABASE_ROOT / f"{label}-{uuid4().hex}.db" for label in labels
    )
    try:
        yield paths
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


def _schema_signature(database_path: Path) -> dict[str, Any]:
    engine = sa.create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        inspector = sa.inspect(engine)
        return {
            table: {
                "columns": [column["name"] for column in inspector.get_columns(table)],
                "indexes": sorted(index["name"] for index in inspector.get_indexes(table)),
                "foreign_keys": sorted(
                    tuple(key["constrained_columns"])
                    for key in inspector.get_foreign_keys(table)
                ),
            }
            for table in sorted(EXPECTED_TABLES)
        }
    finally:
        engine.dispose()


def test_initial_migration_is_reproducible_from_empty_databases() -> None:
    with _database_paths("first", "second") as (first_database, second_database):
        command.upgrade(_config(first_database), "head")
        command.upgrade(_config(second_database), "head")

        assert _schema_signature(first_database) == _schema_signature(second_database)
        assert set(metadata.tables) == EXPECTED_TABLES
        engine = sa.create_engine(f"sqlite:///{first_database.as_posix()}")
        try:
            with engine.connect() as connection:
                context = MigrationContext.configure(connection)
                assert compare_metadata(context, metadata) == []
        finally:
            engine.dispose()


def test_migration_creates_required_tables_correlations_and_indexes() -> None:
    with _database_paths("schema") as (database,):
        command.upgrade(_config(database), "head")
        engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
        try:
            inspector = sa.inspect(engine)
            assert set(inspector.get_table_names()) == EXPECTED_TABLES | {
                "alembic_version"
            }
            assert {
                "ag_ui_thread_id",
                "owner_id",
                "last_run_id",
                "last_action_id",
                "state_schema_version",
            } <= {column["name"] for column in inspector.get_columns("sessions")}
            assert {"a2a_context_id", "remote_task_id"} <= {
                column["name"] for column in inspector.get_columns("agent_tasks")
            }

            indexes = {
                index["name"]
                for table in EXPECTED_TABLES
                for index in inspector.get_indexes(table)
            }
            assert {
                "ix_sessions_thread_updated",
                "ix_sessions_owner_updated",
                "ix_coordinator_runs_session_started",
                "ix_agent_tasks_session_status",
                "ix_agent_tasks_remote_task",
                "ix_evidence_session_retrieved",
                "ix_analysis_session_created",
                "ix_research_artifacts_session_created",
                "ix_recommendation_challenges_session_created",
                "ix_verification_reports_session_created",
                "ix_workflow_transitions_session_occurred",
            } <= indexes
        finally:
            engine.dispose()


def test_upgrade_is_idempotent_and_downgrade_returns_to_base() -> None:
    with _database_paths("round-trip") as (database,):
        config = _config(database)

        command.upgrade(config, "head")
        command.upgrade(config, "head")
        command.downgrade(config, "base")

        engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
        try:
            assert sa.inspect(engine).get_table_names() == ["alembic_version"]
            with engine.connect() as connection:
                rows = connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).all()
                assert rows == []
        finally:
            engine.dispose()


def test_initial_revision_compiles_for_postgresql_without_a_connection() -> None:
    output = io.StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+psycopg://agentdesk:agentdesk@localhost/agentdesk",
    )

    command.upgrade(config, "head", sql=True)

    migration_sql = output.getvalue()
    assert "CREATE TABLE sessions" in migration_sql
    assert "CREATE TABLE agent_tasks" in migration_sql
    assert "CREATE TABLE research_artifacts" in migration_sql
    assert "CREATE TABLE workflow_transitions" in migration_sql
    assert "CREATE INDEX ix_agent_tasks_remote_task" in migration_sql
