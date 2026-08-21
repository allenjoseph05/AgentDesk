"""Durable AG-UI command-to-orchestration integration tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from sqlalchemy.pool import StaticPool

from agents.coordinator.a2a_client import RemoteTaskResult
from agents.coordinator.execution import OrchestrationCommandExecutor
from agents.coordinator.orchestrator import WorkflowExecution
from agents.coordinator.persistence import WorkflowPersistenceService
from agents.coordinator.planner import WorkflowPlan
from agents.coordinator.run_adapter import CoordinatorRunAdapter
from agents.coordinator.workflow_state import WorkflowStateMachine
from packages.contracts import ArtifactEnvelope, ArtifactProvenance, ResearchRequest
from packages.persistence import Database, metadata
from packages.testing import load_research_fixture


class AdvancingClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


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


def _plan() -> WorkflowPlan:
    return WorkflowPlan.model_validate(
        {
            "goal": "compare_options",
            "criteria": ["Data integrity", "Schema flexibility"],
            "steps": [
                {
                    "step_id": "research",
                    "skill": "web-research",
                    "scope": "Collect evidence.",
                    "provider_agent_id": "researcher",
                    "provider_base_url": "https://research.example",
                },
                {
                    "step_id": "analysis",
                    "skill": "decision-analysis",
                    "scope": "Analyze evidence.",
                    "depends_on": ["research"],
                    "provider_agent_id": "analyst",
                    "provider_base_url": "https://analyst.example",
                },
            ],
        }
    )


class RecordingPlanner:
    def __init__(self) -> None:
        self.requests: list[ResearchRequest] = []

    async def plan(self, request: ResearchRequest) -> WorkflowPlan:
        self.requests.append(request)
        return _plan()


class BlockingOrchestrator:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(
        self,
        request: ResearchRequest,
        plan: WorkflowPlan,
    ) -> WorkflowExecution:
        assert request.options == ["PostgreSQL", "MongoDB"]
        assert plan == _plan()
        self.started.set()
        await self.release.wait()
        fixture = load_research_fixture("postgresql-vs-mongodb-golden")
        assert fixture.evidence_bundle is not None
        assert fixture.decision_analysis is not None
        created_at = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
        return WorkflowExecution(
            research=RemoteTaskResult(
                agent_id="researcher",
                remote_task_id="research-task-71",
                remote_context_id="context-71",
                artifact=ArtifactEnvelope(
                    provenance=ArtifactProvenance(
                        producer_agent="researcher",
                        remote_task_id="research-task-71",
                        created_at=created_at,
                    ),
                    payload=fixture.evidence_bundle,
                ),
            ),
            analysis=RemoteTaskResult(
                agent_id="analyst",
                remote_task_id="analysis-task-71",
                remote_context_id="context-71",
                artifact=ArtifactEnvelope(
                    provenance=ArtifactProvenance(
                        producer_agent="analyst",
                        remote_task_id="analysis-task-71",
                        created_at=created_at,
                    ),
                    payload=fixture.decision_analysis,
                ),
            ),
        )


def _input() -> RunAgentInput:
    question = "Should we use PostgreSQL or MongoDB?"
    return RunAgentInput.model_validate(
        {
            "threadId": "browser-thread-71",
            "runId": "coordinator-run-71",
            "state": {},
            "messages": [{"id": "message-71", "role": "user", "content": question}],
            "tools": [],
            "context": [],
            "forwardedProps": {
                "agentdesk": {
                    "schemaVersion": "1.0",
                    "actionId": "action-71",
                    "type": "start_research",
                    "sessionId": None,
                    "payload": {
                        "question": question,
                        "options": ["PostgreSQL", "MongoDB"],
                        "constraints": ["Preserve transactions"],
                        "criteria": ["Data integrity", "Schema flexibility"],
                        "desiredDepth": "normal",
                    },
                }
            },
        }
    )


def _decode(event: str) -> dict[str, Any]:
    return json.loads(event.removeprefix("data: "))


def _follow_up_input() -> RunAgentInput:
    message = "Make the strongest opposing case."
    return RunAgentInput.model_validate(
        {
            "threadId": "browser-thread-71",
            "runId": "follow-up-run-71",
            "state": {
                "schemaVersion": "1.0",
                "sessionId": "coordinator-run-71",
                "question": "Should we use PostgreSQL or MongoDB?",
                "status": "completed",
                "activeStep": None,
                "agents": [],
                "evidence": [],
                "evidenceCount": 0,
                "claims": [],
                "analysis": None,
                "verification": None,
                "warnings": [],
                "errors": [],
                "availableActions": [],
                "lastUpdatedAt": "2026-08-21T12:00:04Z",
            },
            "messages": [{"id": "message-follow-up", "role": "user", "content": message}],
            "tools": [],
            "context": [],
            "forwardedProps": {
                "agentdesk": {
                    "schemaVersion": "1.0",
                    "actionId": "follow-up-action-71",
                    "type": "challenge_recommendation",
                    "sessionId": "coordinator-run-71",
                    "payload": {"challenge": message},
                }
            },
        }
    )


def test_browser_run_stays_open_until_durable_orchestration_boundary(
    database: Database,
) -> None:
    async def scenario() -> tuple[list[dict[str, Any]], RecordingPlanner]:
        planner = RecordingPlanner()
        orchestrator = BlockingOrchestrator()
        executor = OrchestrationCommandExecutor(
            planner=planner,
            orchestrator=orchestrator,
            persistence=WorkflowPersistenceService(database),
            clock=AdvancingClock(),
        )
        stream = CoordinatorRunAdapter(executor=executor).stream(
            _input(),
            EventEncoder(accept="text/event-stream"),
        )

        events = [_decode(await anext(stream)) for _ in range(3)]
        assert [event["type"] for event in events] == [
            "RUN_STARTED",
            "STEP_STARTED",
            "STATE_SNAPSHOT",
        ]
        assert planner.requests == []

        pending_event = asyncio.ensure_future(anext(stream))
        await orchestrator.started.wait()
        await asyncio.sleep(0)
        assert not pending_event.done()
        with database.transaction() as repositories:
            session = repositories.sessions.require("coordinator-run-71")
            run = repositories.runs.get("coordinator-run-71")
        assert session.ag_ui_thread_id == "browser-thread-71"
        assert session.last_run_id == "coordinator-run-71"
        assert session.last_action_id == "action-71"
        assert session.status == "researching"
        assert run is not None and run.status == "running"

        orchestrator.release.set()
        events.append(_decode(await pending_event))
        events.extend([_decode(item) async for item in stream])
        return events, planner

    events, planner = asyncio.run(scenario())

    assert len(planner.requests) == 1
    assert events[-1]["type"] == "RUN_FINISHED"
    assert events[-1]["result"] == {
        "threadId": "browser-thread-71",
        "runId": "coordinator-run-71",
        "sessionId": "coordinator-run-71",
        "actionId": "action-71",
        "status": "completed",
        "remoteTasks": [
            {
                "agentId": "researcher",
                "remoteTaskId": "research-task-71",
                "a2aContextId": "context-71",
            },
            {
                "agentId": "analyst",
                "remoteTaskId": "analysis-task-71",
                "a2aContextId": "context-71",
            },
        ],
    }
    with database.transaction() as repositories:
        session = repositories.sessions.require("coordinator-run-71")
        run = repositories.runs.get("coordinator-run-71")
        transitions = repositories.transitions.list_by_session("coordinator-run-71")
    assert session.status == "completed"
    assert session.completed_steps == ["plan", "research", "analysis"]
    assert run is not None and run.status == "completed"
    assert run.finished_at is not None
    assert [transition.to_status for transition in transitions] == [
        "planning",
        "researching",
        "analyzing",
        "completed",
    ]


def test_follow_up_run_is_correlated_to_existing_thread_and_session(
    database: Database,
) -> None:
    clock = AdvancingClock()
    persistence = WorkflowPersistenceService(database)
    machine = WorkflowStateMachine(
        "coordinator-run-71",
        clock=clock,
        on_transition=persistence.persist_transition,
    )
    persistence.initialize(
        snapshot=machine.snapshot,
        ag_ui_thread_id="browser-thread-71",
        run_id="coordinator-run-71",
        action_id="action-71",
        action_type="start_research",
        question="Should we use PostgreSQL or MongoDB?",
    )
    persistence.start_run("coordinator-run-71")
    machine.transition("planning", active_step="plan")
    machine.transition("researching", active_step="research", completed_steps=["plan"])
    machine.transition("analyzing", active_step="analysis", completed_steps=["research"])
    machine.transition("completed", completed_steps=["analysis"])
    persistence.finish_run(
        "coordinator-run-71",
        status="completed",
        finished_at=machine.snapshot.updated_at,
    )

    planner = RecordingPlanner()
    orchestrator = BlockingOrchestrator()
    executor = OrchestrationCommandExecutor(
        planner=planner,
        orchestrator=orchestrator,
        persistence=persistence,
        clock=clock,
    )

    async def scenario() -> list[dict[str, Any]]:
        return [
            _decode(item)
            async for item in CoordinatorRunAdapter(executor=executor).stream(
                _follow_up_input(),
                EventEncoder(accept="text/event-stream"),
            )
        ]

    events = asyncio.run(scenario())

    assert [event["type"] for event in events] == [
        "RUN_STARTED",
        "STEP_STARTED",
        "STATE_SNAPSHOT",
        "RUN_ERROR",
    ]
    assert events[-1]["code"] == "follow_up_not_implemented"
    assert planner.requests == []
    assert not orchestrator.started.is_set()
    with database.transaction() as repositories:
        session = repositories.sessions.require("coordinator-run-71")
        run = repositories.runs.get("follow-up-run-71")
    assert session.ag_ui_thread_id == "browser-thread-71"
    assert session.last_run_id == "follow-up-run-71"
    assert session.last_action_id == "follow-up-action-71"
    assert session.status == "completed"
    assert run is not None
    assert run.session_id == "coordinator-run-71"
    assert run.status == "failed"
