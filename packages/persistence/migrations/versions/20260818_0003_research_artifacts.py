"""Persist complete research artifact envelopes.

Revision ID: 20260818_0003
Revises: 20260817_0002
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0003"
down_revision: str | None = "20260817_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_artifacts",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("agent_task_id", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("artifact_schema_version", sa.String(length=16), nullable=False),
        sa.Column("producer_agent", sa.String(length=255), nullable=False),
        sa.Column("remote_task_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_research_artifacts_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_task_id"],
            ["agent_tasks.id"],
            name="fk_research_artifacts_agent_task_id_agent_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_research_artifacts"),
        sa.UniqueConstraint(
            "agent_task_id",
            name="uq_research_artifacts_agent_task_id",
        ),
    )
    op.create_index(
        "ix_research_artifacts_session_created",
        "research_artifacts",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_artifacts_session_created",
        table_name="research_artifacts",
    )
    op.drop_table("research_artifacts")
