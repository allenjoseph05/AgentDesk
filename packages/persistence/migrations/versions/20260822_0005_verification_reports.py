"""Persist verification report artifacts.

Revision ID: 20260822_0005
Revises: 20260821_0004
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0005"
down_revision: str | None = "20260821_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_reports",
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
            name="fk_verification_reports_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_task_id"],
            ["agent_tasks.id"],
            name="fk_verification_reports_agent_task_id_agent_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_verification_reports"),
        sa.UniqueConstraint(
            "agent_task_id",
            name="uq_verification_reports_agent_task_id",
        ),
    )
    op.create_index(
        "ix_verification_reports_session_created",
        "verification_reports",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_verification_reports_session_created",
        table_name="verification_reports",
    )
    op.drop_table("verification_reports")
