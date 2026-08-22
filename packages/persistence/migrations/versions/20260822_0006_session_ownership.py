"""Bind durable sessions to an authenticated principal.

Revision ID: 20260822_0006
Revises: 20260822_0005
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0006"
down_revision: str | None = "20260822_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "owner_id",
            sa.String(length=255),
            nullable=False,
            server_default="local-development",
        ),
    )
    op.create_index(
        "ix_sessions_owner_updated",
        "sessions",
        ["owner_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_owner_updated", table_name="sessions")
    op.drop_column("sessions", "owner_id")
