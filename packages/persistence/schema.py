"""Canonical relational schema for durable Coordinator workflow state."""

from __future__ import annotations

import sqlalchemy as sa

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)

sessions = sa.Table(
    "sessions",
    metadata,
    sa.Column("id", sa.String(255), primary_key=True),
    sa.Column(
        "owner_id",
        sa.String(255),
        nullable=False,
        server_default="local-development",
    ),
    sa.Column("ag_ui_thread_id", sa.String(255), nullable=False),
    sa.Column("last_run_id", sa.String(255)),
    sa.Column("last_action_id", sa.String(255)),
    sa.Column("state_schema_version", sa.String(16), nullable=False, server_default="1.0"),
    sa.Column("question", sa.Text(), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("active_step", sa.String(255)),
    sa.Column("completed_steps", sa.JSON(), nullable=False),
    sa.Column("failed_steps", sa.JSON(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "status IN ('created', 'scoping', 'awaiting_input', 'planning', "
        "'researching', 'analyzing', "
        "'verifying', 'cancelling', 'completed', 'partial', 'failed', 'cancelled')",
        name="status",
    ),
)
sa.Index("ix_sessions_thread_updated", sessions.c.ag_ui_thread_id, sessions.c.updated_at)
sa.Index("ix_sessions_owner_updated", sessions.c.owner_id, sessions.c.updated_at)
sa.Index("ix_sessions_status_updated", sessions.c.status, sessions.c.updated_at)

workflow_transitions = sa.Table(
    "workflow_transitions",
    metadata,
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("sequence", sa.Integer(), primary_key=True),
    sa.Column("from_status", sa.String(32), nullable=False),
    sa.Column("to_status", sa.String(32), nullable=False),
    sa.Column("active_step", sa.String(255)),
    sa.Column("reason", sa.Text()),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("sequence >= 1", name="positive_sequence"),
)
sa.Index(
    "ix_workflow_transitions_session_occurred",
    workflow_transitions.c.session_id,
    workflow_transitions.c.occurred_at,
)

coordinator_runs = sa.Table(
    "coordinator_runs",
    metadata,
    sa.Column("run_id", sa.String(255), primary_key=True),
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("ag_ui_thread_id", sa.String(255), nullable=False),
    sa.Column("action_id", sa.String(255), nullable=False, unique=True),
    sa.Column("action_type", sa.String(64), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint(
        "status IN ('accepted', 'running', 'completed', 'partial', 'failed', 'cancelled')",
        name="status",
    ),
)
sa.Index(
    "ix_coordinator_runs_session_started",
    coordinator_runs.c.session_id,
    coordinator_runs.c.started_at,
)
sa.Index(
    "ix_coordinator_runs_thread_started",
    coordinator_runs.c.ag_ui_thread_id,
    coordinator_runs.c.started_at,
)

agent_tasks = sa.Table(
    "agent_tasks",
    metadata,
    sa.Column("id", sa.String(255), primary_key=True),
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "run_id",
        sa.String(255),
        sa.ForeignKey("coordinator_runs.run_id", ondelete="SET NULL"),
    ),
    sa.Column("agent_id", sa.String(255), nullable=False),
    sa.Column("skill", sa.String(255), nullable=False),
    sa.Column("a2a_context_id", sa.String(255)),
    sa.Column("remote_task_id", sa.String(255)),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("error_code", sa.String(128)),
    sa.Column("error_message", sa.Text()),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint(
        "status IN ('pending', 'submitted', 'working', 'completed', 'failed', 'cancelled')",
        name="status",
    ),
    sa.UniqueConstraint("agent_id", "remote_task_id"),
)
sa.Index("ix_agent_tasks_session_status", agent_tasks.c.session_id, agent_tasks.c.status)
sa.Index("ix_agent_tasks_remote_task", agent_tasks.c.remote_task_id)
sa.Index("ix_agent_tasks_a2a_context", agent_tasks.c.a2a_context_id)

intake_proposals = sa.Table(
    "intake_proposals",
    metadata,
    sa.Column("proposal_id", sa.String(255), primary_key=True),
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "agent_task_id",
        sa.String(255),
        sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column("request_payload", sa.JSON(), nullable=False),
    sa.Column("artifact_payload", sa.JSON(), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("normalized_request", sa.JSON()),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("decided_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint(
        "status IN ('awaiting_response', 'accepted', 'skipped')",
        name="status",
    ),
)
sa.Index(
    "ix_intake_proposals_session_status", intake_proposals.c.session_id, intake_proposals.c.status
)

intake_responses = sa.Table(
    "intake_responses",
    metadata,
    sa.Column("action_id", sa.String(255), primary_key=True),
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column(
        "proposal_id",
        sa.String(255),
        sa.ForeignKey("intake_proposals.proposal_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column("response_payload", sa.JSON(), nullable=False),
    sa.Column("normalized_request", sa.JSON(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
sa.Index(
    "ix_intake_responses_session_created",
    intake_responses.c.session_id,
    intake_responses.c.created_at,
)

evidence = sa.Table(
    "evidence",
    metadata,
    sa.Column("id", sa.String(255), primary_key=True),
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "agent_task_id",
        sa.String(255),
        sa.ForeignKey("agent_tasks.id", ondelete="SET NULL"),
    ),
    sa.Column("evidence_id", sa.String(255), nullable=False),
    sa.Column("title", sa.Text(), nullable=False),
    sa.Column("source_url", sa.Text()),
    sa.Column("source_type", sa.String(64), nullable=False),
    sa.Column("summary", sa.Text(), nullable=False),
    sa.Column("relevance", sa.Float(), nullable=False),
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("artifact_schema_version", sa.String(16), nullable=False),
    sa.UniqueConstraint("session_id", "evidence_id"),
    sa.CheckConstraint("relevance >= 0 AND relevance <= 1", name="relevance"),
)
sa.Index("ix_evidence_session_retrieved", evidence.c.session_id, evidence.c.retrieved_at)
sa.Index("ix_evidence_agent_task", evidence.c.agent_task_id)

claims = sa.Table(
    "claims",
    metadata,
    sa.Column("id", sa.String(255), primary_key=True),
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "agent_task_id",
        sa.String(255),
        sa.ForeignKey("agent_tasks.id", ondelete="SET NULL"),
    ),
    sa.Column("claim_id", sa.String(255), nullable=False),
    sa.Column("statement", sa.Text(), nullable=False),
    sa.Column("evidence_ids", sa.JSON(), nullable=False),
    sa.Column("confidence", sa.Float()),
    sa.Column("caveats", sa.JSON(), nullable=False),
    sa.Column("artifact_schema_version", sa.String(16), nullable=False),
    sa.UniqueConstraint("session_id", "claim_id"),
    sa.CheckConstraint(
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
        name="confidence",
    ),
)
sa.Index("ix_claims_session", claims.c.session_id)
sa.Index("ix_claims_agent_task", claims.c.agent_task_id)

research_artifacts = sa.Table(
    "research_artifacts",
    metadata,
    sa.Column("id", sa.String(255), primary_key=True),
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "agent_task_id",
        sa.String(255),
        sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column("payload", sa.JSON(), nullable=False),
    sa.Column("artifact_schema_version", sa.String(16), nullable=False),
    sa.Column("producer_agent", sa.String(255), nullable=False),
    sa.Column("remote_task_id", sa.String(255), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
sa.Index(
    "ix_research_artifacts_session_created",
    research_artifacts.c.session_id,
    research_artifacts.c.created_at,
)

analysis = sa.Table(
    "analysis",
    metadata,
    sa.Column("id", sa.String(255), primary_key=True),
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "agent_task_id",
        sa.String(255),
        sa.ForeignKey("agent_tasks.id", ondelete="SET NULL"),
        unique=True,
    ),
    sa.Column("recommendation", sa.Text(), nullable=False),
    sa.Column("payload", sa.JSON(), nullable=False),
    sa.Column("artifact_schema_version", sa.String(16), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
sa.Index("ix_analysis_session_created", analysis.c.session_id, analysis.c.created_at)

recommendation_challenges = sa.Table(
    "recommendation_challenges",
    metadata,
    sa.Column("id", sa.String(255), primary_key=True),
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "agent_task_id",
        sa.String(255),
        sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column("payload", sa.JSON(), nullable=False),
    sa.Column("artifact_schema_version", sa.String(16), nullable=False),
    sa.Column("producer_agent", sa.String(255), nullable=False),
    sa.Column("remote_task_id", sa.String(255), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
sa.Index(
    "ix_recommendation_challenges_session_created",
    recommendation_challenges.c.session_id,
    recommendation_challenges.c.created_at,
)

verification_reports = sa.Table(
    "verification_reports",
    metadata,
    sa.Column("id", sa.String(255), primary_key=True),
    sa.Column(
        "session_id",
        sa.String(255),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "agent_task_id",
        sa.String(255),
        sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    sa.Column("payload", sa.JSON(), nullable=False),
    sa.Column("artifact_schema_version", sa.String(16), nullable=False),
    sa.Column("producer_agent", sa.String(255), nullable=False),
    sa.Column("remote_task_id", sa.String(255), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
sa.Index(
    "ix_verification_reports_session_created",
    verification_reports.c.session_id,
    verification_reports.c.created_at,
)
