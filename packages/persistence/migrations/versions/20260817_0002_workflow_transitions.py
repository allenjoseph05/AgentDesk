"""Persist ordered Coordinator workflow transitions.

Revision ID: 20260817_0002
Revises: 20260817_0001
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0002"
down_revision: str | None = "20260817_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_transitions",
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=False),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("active_step", sa.String(length=255)),
        sa.Column("reason", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence >= 1",
            name="ck_workflow_transitions_positive_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_workflow_transitions_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "session_id",
            "sequence",
            name="pk_workflow_transitions",
        ),
    )
    op.create_index(
        "ix_workflow_transitions_session_occurred",
        "workflow_transitions",
        ["session_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_transitions_session_occurred",
        table_name="workflow_transitions",
    )
    op.drop_table("workflow_transitions")
