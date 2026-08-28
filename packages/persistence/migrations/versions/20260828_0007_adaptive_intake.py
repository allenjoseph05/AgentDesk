"""Persist adaptive-intake proposals and responses.

Revision ID: 20260828_0007
Revises: 20260822_0006
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0007"
down_revision: str | None = "20260822_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_constraint("ck_sessions_status", type_="check")
        batch.create_check_constraint(
            "ck_sessions_status",
            "status IN ('created', 'scoping', 'awaiting_input', 'planning', "
            "'researching', 'analyzing', 'verifying', 'cancelling', 'completed', "
            "'partial', 'failed', 'cancelled')",
        )
    op.create_table(
        "intake_proposals",
        sa.Column("proposal_id", sa.String(length=255), primary_key=True),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("agent_task_id", sa.String(length=255), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("artifact_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("normalized_request", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('awaiting_response', 'accepted', 'skipped')",
            name="ck_intake_proposals_status",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_task_id"], ["agent_tasks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("session_id", name="uq_intake_proposals_session_id"),
        sa.UniqueConstraint("agent_task_id", name="uq_intake_proposals_agent_task_id"),
    )
    op.create_index(
        "ix_intake_proposals_session_status",
        "intake_proposals",
        ["session_id", "status"],
    )
    op.create_table(
        "intake_responses",
        sa.Column("action_id", sa.String(length=255), primary_key=True),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("proposal_id", sa.String(length=255), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("normalized_request", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["intake_proposals.proposal_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("session_id", name="uq_intake_responses_session_id"),
        sa.UniqueConstraint("proposal_id", name="uq_intake_responses_proposal_id"),
    )
    op.create_index(
        "ix_intake_responses_session_created",
        "intake_responses",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_intake_responses_session_created", table_name="intake_responses")
    op.drop_table("intake_responses")
    op.drop_index("ix_intake_proposals_session_status", table_name="intake_proposals")
    op.drop_table("intake_proposals")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_constraint("ck_sessions_status", type_="check")
        batch.create_check_constraint(
            "ck_sessions_status",
            "status IN ('created', 'planning', 'researching', 'analyzing', 'verifying', "
            "'cancelling', 'completed', 'partial', 'failed', 'cancelled')",
        )
