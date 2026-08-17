"""Create the initial AgentDesk persistence schema.

Revision ID: 20260817_0001
Revises: None
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("ag_ui_thread_id", sa.String(length=255), nullable=False),
        sa.Column("last_run_id", sa.String(length=255)),
        sa.Column("last_action_id", sa.String(length=255)),
        sa.Column(
            "state_schema_version",
            sa.String(length=16),
            server_default="1.0",
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_step", sa.String(length=255)),
        sa.Column("completed_steps", sa.JSON(), nullable=False),
        sa.Column("failed_steps", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('created', 'planning', 'researching', 'analyzing', "
            "'verifying', 'cancelling', 'completed', 'partial', 'failed', 'cancelled')",
            name="ck_sessions_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
    )
    op.create_index(
        "ix_sessions_thread_updated",
        "sessions",
        ["ag_ui_thread_id", "updated_at"],
    )
    op.create_index("ix_sessions_status_updated", "sessions", ["status", "updated_at"])

    op.create_table(
        "coordinator_runs",
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("ag_ui_thread_id", sa.String(length=255), nullable=False),
        sa.Column("action_id", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('accepted', 'running', 'completed', 'partial', "
            "'failed', 'cancelled')",
            name="ck_coordinator_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_coordinator_runs_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_coordinator_runs"),
        sa.UniqueConstraint("action_id", name="uq_coordinator_runs_action_id"),
    )
    op.create_index(
        "ix_coordinator_runs_session_started",
        "coordinator_runs",
        ["session_id", "started_at"],
    )
    op.create_index(
        "ix_coordinator_runs_thread_started",
        "coordinator_runs",
        ["ag_ui_thread_id", "started_at"],
    )

    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=255)),
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column("skill", sa.String(length=255), nullable=False),
        sa.Column("a2a_context_id", sa.String(length=255)),
        sa.Column("remote_task_id", sa.String(length=255)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=128)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending', 'submitted', 'working', 'completed', "
            "'failed', 'cancelled')",
            name="ck_agent_tasks_status",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["coordinator_runs.run_id"],
            name="fk_agent_tasks_run_id_coordinator_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_agent_tasks_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_tasks"),
        sa.UniqueConstraint(
            "agent_id",
            "remote_task_id",
            name="uq_agent_tasks_agent_id_remote_task_id",
        ),
    )
    op.create_index("ix_agent_tasks_a2a_context", "agent_tasks", ["a2a_context_id"])
    op.create_index("ix_agent_tasks_remote_task", "agent_tasks", ["remote_task_id"])
    op.create_index(
        "ix_agent_tasks_session_status",
        "agent_tasks",
        ["session_id", "status"],
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("agent_task_id", sa.String(length=255)),
        sa.Column("evidence_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("artifact_schema_version", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "relevance >= 0 AND relevance <= 1",
            name="ck_evidence_relevance",
        ),
        sa.ForeignKeyConstraint(
            ["agent_task_id"],
            ["agent_tasks.id"],
            name="fk_evidence_agent_task_id_agent_tasks",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_evidence_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence"),
        sa.UniqueConstraint(
            "session_id",
            "evidence_id",
            name="uq_evidence_session_id_evidence_id",
        ),
    )
    op.create_index("ix_evidence_agent_task", "evidence", ["agent_task_id"])
    op.create_index(
        "ix_evidence_session_retrieved",
        "evidence",
        ["session_id", "retrieved_at"],
    )

    op.create_table(
        "claims",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("agent_task_id", sa.String(length=255)),
        sa.Column("claim_id", sa.String(length=255), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("caveats", sa.JSON(), nullable=False),
        sa.Column("artifact_schema_version", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_claims_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["agent_task_id"],
            ["agent_tasks.id"],
            name="fk_claims_agent_task_id_agent_tasks",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_claims_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_claims"),
        sa.UniqueConstraint(
            "session_id",
            "claim_id",
            name="uq_claims_session_id_claim_id",
        ),
    )
    op.create_index("ix_claims_agent_task", "claims", ["agent_task_id"])
    op.create_index("ix_claims_session", "claims", ["session_id"])

    op.create_table(
        "analysis",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("agent_task_id", sa.String(length=255)),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("artifact_schema_version", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_task_id"],
            ["agent_tasks.id"],
            name="fk_analysis_agent_task_id_agent_tasks",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_analysis_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis"),
        sa.UniqueConstraint("agent_task_id", name="uq_analysis_agent_task_id"),
    )
    op.create_index(
        "ix_analysis_session_created",
        "analysis",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_session_created", table_name="analysis")
    op.drop_table("analysis")
    op.drop_index("ix_claims_session", table_name="claims")
    op.drop_index("ix_claims_agent_task", table_name="claims")
    op.drop_table("claims")
    op.drop_index("ix_evidence_session_retrieved", table_name="evidence")
    op.drop_index("ix_evidence_agent_task", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_agent_tasks_session_status", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_remote_task", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_a2a_context", table_name="agent_tasks")
    op.drop_table("agent_tasks")
    op.drop_index("ix_coordinator_runs_thread_started", table_name="coordinator_runs")
    op.drop_index("ix_coordinator_runs_session_started", table_name="coordinator_runs")
    op.drop_table("coordinator_runs")
    op.drop_index("ix_sessions_status_updated", table_name="sessions")
    op.drop_index("ix_sessions_thread_updated", table_name="sessions")
    op.drop_table("sessions")
