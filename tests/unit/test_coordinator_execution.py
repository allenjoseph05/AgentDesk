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

from agents.analyst.agent_card import create_agent_card as create_analyst_card
from agents.coordinator.a2a_client import RemoteTaskResult
from agents.coordinator.execution import OrchestrationCommandExecutor
from agents.coordinator.history import ResearchHistoryService
from agents.coordinator.orchestrator import WorkflowExecution
from agents.coordinator.persistence import WorkflowPersistenceService
from agents.coordinator.planner import WorkflowPlan
from agents.coordinator.projection import (
    DurableAgUiProjector,
    apply_projected_delta,
)
from agents.coordinator.registry import RegisteredAgent
from agents.coordinator.run_adapter import CoordinatorRunAdapter
from agents.coordinator.workflow_state import WorkflowStateMachine
from agents.researcher.agent_card import create_agent_card as create_research_card
from agents.verifier.agent_card import create_agent_card as create_verifier_card
from packages.contracts import (
    AgentDeskViewState,
    AnalysisRequest,
    ArtifactEnvelope,
    ArtifactProvenance,
    EvidenceBundle,
    RecommendationChallenge,
    ResearchRequest,
    VerificationReport,
)
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
    def __init__(
        self,
        *,
        fixture_id: str = "postgresql-vs-mongodb-golden",
        fail_analysis: bool = False,
        fail_verification: bool = False,
        emit_late_task_on_cancel: bool = False,
    ) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.fixture_id = fixture_id
        self.fail_analysis = fail_analysis
        self.fail_verification = fail_verification
        self.emit_late_task_on_cancel = emit_late_task_on_cancel
        self.challenge_requests: list[AnalysisRequest] = []
        self.execute_calls = 0
        self.cancel_calls: list[tuple[str, str, float]] = []

    async def execute(
        self,
        request: ResearchRequest,
        plan: WorkflowPlan,
        **callbacks: Any,
    ) -> WorkflowExecution:
        self.execute_calls += 1
        research_remote_task_id = f"research-task-{70 + self.execute_calls}"
        analysis_remote_task_id = f"analysis-task-{70 + self.execute_calls}"
        assert request.options == ["PostgreSQL", "MongoDB"]
        assert plan == _plan()
        research_agent = RegisteredAgent(
            agent_id="researcher",
            base_url="https://research.example",
            card=create_research_card("https://research.example"),
        )
        on_started = callbacks.get("on_remote_task_started")
        if on_started is not None:
            await on_started(research_agent, research_remote_task_id)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            if self.emit_late_task_on_cancel and on_started is not None:
                late_agent = RegisteredAgent(
                    agent_id="analyst",
                    base_url="https://analyst.example",
                    card=create_analyst_card("https://analyst.example"),
                )
                await on_started(late_agent, "analysis-late-task-75")
            raise
        fixture = load_research_fixture(self.fixture_id)
        assert fixture.evidence_bundle is not None
        assert fixture.decision_analysis is not None
        created_at = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
        execution = WorkflowExecution(
            research=RemoteTaskResult(
                agent_id="researcher",
                remote_task_id=research_remote_task_id,
                remote_context_id="context-71",
                artifact=ArtifactEnvelope(
                    provenance=ArtifactProvenance(
                        producer_agent="researcher",
                        remote_task_id=research_remote_task_id,
                        created_at=created_at,
                    ),
                    payload=fixture.evidence_bundle,
                ),
            ),
            analysis=RemoteTaskResult(
                agent_id="analyst",
                remote_task_id=analysis_remote_task_id,
                remote_context_id="context-71",
                artifact=ArtifactEnvelope(
                    provenance=ArtifactProvenance(
                        producer_agent="analyst",
                        remote_task_id=analysis_remote_task_id,
                        created_at=created_at,
                    ),
                    payload=fixture.decision_analysis,
                ),
            ),
        )
        on_research_completed = callbacks.get("on_research_completed")
        if on_research_completed is not None:
            await on_research_completed(research_agent, execution.research)
            await on_research_completed(research_agent, execution.research)
        analysis_agent = RegisteredAgent(
            agent_id="analyst",
            base_url="https://analyst.example",
            card=create_analyst_card("https://analyst.example"),
        )
        if on_started is not None:
            await on_started(analysis_agent, analysis_remote_task_id)
        if self.fail_analysis:
            raise RuntimeError("Analyst fixture failure.")
        on_analysis_completed = callbacks.get("on_analysis_completed")
        if on_analysis_completed is not None:
            await on_analysis_completed(analysis_agent, execution.analysis)
            await on_analysis_completed(analysis_agent, execution.analysis)
        return execution

    async def verify(
        self,
        evidence_bundle: EvidenceBundle,
        **callbacks: Any,
    ) -> RemoteTaskResult[VerificationReport]:
        fixture = load_research_fixture(self.fixture_id)
        assert fixture.evidence_bundle == evidence_bundle
        assert fixture.verification_report is not None
        agent = RegisteredAgent(
            agent_id="verifier",
            base_url="https://verifier.example",
            card=create_verifier_card("https://verifier.example"),
        )
        on_scheduled = callbacks.get("on_verification_scheduled")
        if on_scheduled is not None:
            await on_scheduled(agent)
        on_started = callbacks.get("on_remote_task_started")
        if on_started is not None:
            await on_started(agent, "verification-task-71")
        try:
            if self.fail_verification:
                raise RuntimeError("Verifier fixture failure.")
            return RemoteTaskResult(
                agent_id="verifier",
                remote_task_id="verification-task-71",
                remote_context_id="context-71",
                artifact=ArtifactEnvelope(
                    provenance=ArtifactProvenance(
                        producer_agent="verifier",
                        remote_task_id="verification-task-71",
                        created_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
                    ),
                    payload=fixture.verification_report,
                ),
            )
        finally:
            on_finished = callbacks.get("on_remote_task_finished")
            if on_finished is not None:
                await on_finished(agent, "verification-task-71")

    async def cancel(self, **kwargs: Any) -> None:
        self.cancel_calls.append(
            (
                kwargs["agent"].agent_id,
                kwargs["remote_task_id"],
                kwargs["timeout_seconds"],
            )
        )

    async def challenge(
        self,
        request: AnalysisRequest,
        **callbacks: Any,
    ) -> RemoteTaskResult[RecommendationChallenge]:
        del callbacks
        self.challenge_requests.append(request)
        fixture = load_research_fixture("postgresql-vs-mongodb-golden")
        assert fixture.recommendation_challenge is not None
        return RemoteTaskResult(
            agent_id="analyst",
            remote_task_id=f"challenge-task-{len(self.challenge_requests)}",
            remote_context_id="context-71",
            artifact=ArtifactEnvelope(
                provenance=ArtifactProvenance(
                    producer_agent="analyst",
                    remote_task_id=f"challenge-task-{len(self.challenge_requests)}",
                    created_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
                ),
                payload=fixture.recommendation_challenge,
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
                "recommendationChallenge": None,
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


def _research_follow_up_input(
    *,
    run_id: str,
    action_id: str,
    action_type: str,
    payload: dict[str, Any],
) -> RunAgentInput:
    return RunAgentInput.model_validate(
        {
            "threadId": "browser-thread-71",
            "runId": run_id,
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
                "recommendationChallenge": None,
                "verification": None,
                "warnings": [],
                "errors": [],
                "availableActions": [],
                "lastUpdatedAt": "2026-08-21T12:00:04Z",
            },
            "messages": [
                {
                    "id": f"message-{action_id}",
                    "role": "user",
                    "content": "Continue the decision research.",
                }
            ],
            "tools": [],
            "context": [],
            "forwardedProps": {
                "agentdesk": {
                    "schemaVersion": "1.0",
                    "actionId": action_id,
                    "type": action_type,
                    "sessionId": "coordinator-run-71",
                    "payload": payload,
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
            projector=DurableAgUiProjector(database),
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

        events.extend([_decode(await anext(stream)) for _ in range(5)])
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
    research_steps = [
        event
        for event in events
        if event["type"] in {"STEP_STARTED", "STEP_FINISHED"}
        and event.get("stepName") == "research"
    ]
    assert [event["type"] for event in research_steps] == [
        "STEP_STARTED",
        "STEP_FINISHED",
    ]
    activities = [
        event
        for event in events
        if event["type"] == "ACTIVITY_SNAPSHOT"
        and event["activityType"] == "specialist-research"
    ]
    assert [event["content"]["status"] for event in activities] == [
        "waiting",
        "working",
        "completed",
    ]
    assert len({event["messageId"] for event in activities}) == 1
    analysis_steps = [
        event
        for event in events
        if event["type"] in {"STEP_STARTED", "STEP_FINISHED"}
        and event.get("stepName") == "analysis"
    ]
    assert [event["type"] for event in analysis_steps] == [
        "STEP_STARTED",
        "STEP_FINISHED",
    ]
    analysis_activities = [
        event
        for event in events
        if event["type"] == "ACTIVITY_SNAPSHOT"
        and event["activityType"] == "specialist-analysis"
    ]
    assert [event["content"]["status"] for event in analysis_activities] == [
        "waiting",
        "working",
        "completed",
    ]
    assert len({event["messageId"] for event in analysis_activities}) == 1
    verification_steps = [
        event
        for event in events
        if event["type"] in {"STEP_STARTED", "STEP_FINISHED"}
        and event.get("stepName") == "verification"
    ]
    assert [event["type"] for event in verification_steps] == [
        "STEP_STARTED",
        "STEP_FINISHED",
    ]
    verification_activities = [
        event
        for event in events
        if event["type"] == "ACTIVITY_SNAPSHOT"
        and event["activityType"] == "specialist-verification"
    ]
    assert [event["content"]["status"] for event in verification_activities] == [
        "waiting",
        "working",
        "completed",
    ]
    evidence_delta = next(
        event
        for event in events
        if event["type"] == "STATE_DELTA"
        and any(operation["path"] == "/evidence" for operation in event["delta"])
    )
    evidence_paths = {operation["path"] for operation in evidence_delta["delta"]}
    assert {"/evidence", "/evidenceCount", "/claims"} <= evidence_paths
    analysis_delta = next(
        event
        for event in events
        if event["type"] == "STATE_DELTA"
        and any(operation["path"] == "/analysis" for operation in event["delta"])
    )
    projected_analysis = next(
        operation["value"]
        for operation in analysis_delta["delta"]
        if operation["path"] == "/analysis"
    )
    assert projected_analysis["recommendation"] == "PostgreSQL"
    assert projected_analysis["criteria"]
    assert projected_analysis["risks"]
    assert projected_analysis["assumptions"]
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
            {
                "agentId": "verifier",
                "remoteTaskId": "verification-task-71",
                "a2aContextId": "context-71",
            },
        ],
    }
    with database.transaction() as repositories:
        session = repositories.sessions.require("coordinator-run-71")
        run = repositories.runs.get("coordinator-run-71")
        transitions = repositories.transitions.list_by_session("coordinator-run-71")
        evidence = repositories.artifacts.list_evidence("coordinator-run-71")
        claims = repositories.artifacts.list_claims("coordinator-run-71")
        analyses = repositories.artifacts.list_analysis("coordinator-run-71")
        verification_reports = repositories.artifacts.list_verification_reports(
            "coordinator-run-71"
        )
        tasks = repositories.agent_tasks.list_by_session("coordinator-run-71")
    assert session.status == "completed"
    assert session.completed_steps == ["plan", "research", "analysis", "verification"]
    assert run is not None and run.status == "completed"
    assert run.finished_at is not None
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    assert len(evidence) == len(fixture.evidence_bundle.evidence)
    assert len(claims) == len(fixture.evidence_bundle.claims)
    assert len(analyses) == 1
    assert analyses[0].analysis == fixture.decision_analysis
    assert len(verification_reports) == 1
    assert verification_reports[0].envelope.payload == fixture.verification_report
    assert [(task.agent_id, task.status) for task in tasks] == [
        ("analyst", "completed"),
        ("researcher", "completed"),
        ("verifier", "completed"),
    ]
    assert [transition.to_status for transition in transitions] == [
        "planning",
        "researching",
        "analyzing",
        "verifying",
        "completed",
    ]


def test_analysis_failure_finishes_partial_and_preserves_evidence(
    database: Database,
) -> None:
    async def scenario() -> list[dict[str, Any]]:
        orchestrator = BlockingOrchestrator(
            fixture_id="postgresql-vs-mongodb-partial",
            fail_analysis=True,
        )
        orchestrator.release.set()
        executor = OrchestrationCommandExecutor(
            planner=RecordingPlanner(),
            orchestrator=orchestrator,
            persistence=WorkflowPersistenceService(database),
            projector=DurableAgUiProjector(database),
            clock=AdvancingClock(),
        )
        return [
            _decode(item)
            async for item in CoordinatorRunAdapter(executor=executor).stream(
                _input(),
                EventEncoder(accept="text/event-stream"),
            )
        ]

    events = asyncio.run(scenario())

    assert not any(event["type"] == "RUN_ERROR" for event in events)
    assert events[-1]["type"] == "RUN_FINISHED"
    assert events[-1]["result"]["status"] == "partial"
    snapshot_event = next(event for event in events if event["type"] == "STATE_SNAPSHOT")
    state = AgentDeskViewState.model_validate(snapshot_event["snapshot"])
    for event in events:
        if event["type"] == "STATE_DELTA":
            state = apply_projected_delta(state, event["delta"])
    fixture = load_research_fixture("postgresql-vs-mongodb-partial")
    assert fixture.evidence_bundle is not None
    assert state.status == "partial"
    assert {item.id: item for item in state.evidence} == {
        item.id: item for item in fixture.evidence_bundle.evidence
    }
    assert {item.id: item for item in state.claims} == {
        item.id: item for item in fixture.evidence_bundle.claims
    }
    assert state.analysis is None
    assert state.verification is None
    assert [(agent.agent_id, agent.status) for agent in state.agents] == [
        ("analyst", "failed"),
        ("researcher", "completed"),
    ]
    with database.transaction() as repositories:
        run = repositories.runs.get("coordinator-run-71")
        analyses = repositories.artifacts.list_analysis("coordinator-run-71")
    assert run is not None and run.status == "partial"
    assert analyses == ()


def test_verification_failure_preserves_successful_research_and_analysis(
    database: Database,
) -> None:
    async def scenario() -> list[dict[str, Any]]:
        orchestrator = BlockingOrchestrator(fail_verification=True)
        orchestrator.release.set()
        executor = OrchestrationCommandExecutor(
            planner=RecordingPlanner(),
            orchestrator=orchestrator,
            persistence=WorkflowPersistenceService(database),
            projector=DurableAgUiProjector(database),
            clock=AdvancingClock(),
        )
        return [
            _decode(item)
            async for item in CoordinatorRunAdapter(executor=executor).stream(
                _input(),
                EventEncoder(accept="text/event-stream"),
            )
        ]

    events = asyncio.run(scenario())

    assert not any(event["type"] == "RUN_ERROR" for event in events)
    assert events[-1]["type"] == "RUN_FINISHED"
    assert events[-1]["result"]["status"] == "partial"
    assert [
        task["agentId"] for task in events[-1]["result"]["remoteTasks"]
    ] == ["researcher", "analyst"]

    snapshot_event = next(event for event in events if event["type"] == "STATE_SNAPSHOT")
    state = AgentDeskViewState.model_validate(snapshot_event["snapshot"])
    for event in events:
        if event["type"] == "STATE_DELTA":
            state = apply_projected_delta(state, event["delta"])
    fixture = load_research_fixture("postgresql-vs-mongodb-golden")
    assert fixture.evidence_bundle is not None
    assert fixture.decision_analysis is not None
    assert state.status == "partial"
    assert {item.id: item for item in state.evidence} == {
        item.id: item for item in fixture.evidence_bundle.evidence
    }
    assert {item.id: item for item in state.claims} == {
        item.id: item for item in fixture.evidence_bundle.claims
    }
    assert state.analysis == fixture.decision_analysis
    assert state.verification is None
    assert [(agent.agent_id, agent.status) for agent in state.agents] == [
        ("analyst", "completed"),
        ("researcher", "completed"),
        ("verifier", "failed"),
    ]

    with database.transaction() as repositories:
        run = repositories.runs.get("coordinator-run-71")
        analyses = repositories.artifacts.list_analysis("coordinator-run-71")
        verification_reports = repositories.artifacts.list_verification_reports(
            "coordinator-run-71"
        )
        transitions = repositories.transitions.list_by_session("coordinator-run-71")
    assert run is not None and run.status == "partial"
    assert len(analyses) == 1
    assert analyses[0].analysis == fixture.decision_analysis
    assert verification_reports == ()
    assert [transition.to_status for transition in transitions] == [
        "planning",
        "researching",
        "analyzing",
        "verifying",
        "partial",
    ]


def test_browser_abort_cancels_remote_tasks_and_rehydrates_terminal_state(
    database: Database,
) -> None:
    orchestrator = BlockingOrchestrator(emit_late_task_on_cancel=True)
    executor = OrchestrationCommandExecutor(
        planner=RecordingPlanner(),
        orchestrator=orchestrator,
        persistence=WorkflowPersistenceService(database),
        projector=DurableAgUiProjector(database),
        clock=AdvancingClock(),
    )
    adapter = CoordinatorRunAdapter(executor=executor)

    async def scenario() -> None:
        stream = adapter.stream(
            _input(),
            EventEncoder(accept="text/event-stream"),
        )

        async def consume() -> None:
            _ = [_decode(item) async for item in stream]

        consumer = asyncio.create_task(consume())
        await orchestrator.started.wait()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer

    asyncio.run(scenario())

    assert [(agent_id, task_id) for agent_id, task_id, _ in orchestrator.cancel_calls] == [
        ("researcher", "research-task-71"),
        ("analyst", "analysis-late-task-75"),
    ]
    with database.transaction() as repositories:
        session = repositories.sessions.require("coordinator-run-71")
        run = repositories.runs.get("coordinator-run-71")
        tasks = repositories.agent_tasks.list_by_session("coordinator-run-71")
        transitions = repositories.transitions.list_by_session("coordinator-run-71")
    assert session.status == "cancelled"
    assert run is not None and run.status == "cancelled"
    assert [(task.agent_id, task.status) for task in tasks] == [
        ("analyst", "cancelled"),
        ("researcher", "cancelled"),
    ]
    analyst_task = next(task for task in tasks if task.agent_id == "analyst")
    assert analyst_task.remote_task_id == "analysis-late-task-75"
    assert [transition.to_status for transition in transitions[-2:]] == [
        "cancelling",
        "cancelled",
    ]

    rehydrated = ResearchHistoryService(database).get_terminal_session(
        "coordinator-run-71"
    )
    assert rehydrated.state.status == "cancelled"
    assert [(agent.agent_id, agent.status) for agent in rehydrated.state.agents] == [
        ("analyst", "cancelled"),
        ("researcher", "cancelled"),
    ]
    assert rehydrated.state.analysis is None


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
        projector=DurableAgUiProjector(database),
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
    assert events[-1]["code"] == "orchestration_failed"
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


def test_challenge_creates_one_new_run_and_live_counteranalysis_delta(
    database: Database,
) -> None:
    planner = RecordingPlanner()
    orchestrator = BlockingOrchestrator()
    orchestrator.release.set()
    adapter = CoordinatorRunAdapter(
        executor=OrchestrationCommandExecutor(
            planner=planner,
            orchestrator=orchestrator,
            persistence=WorkflowPersistenceService(database),
            projector=DurableAgUiProjector(database),
            clock=AdvancingClock(),
        )
    )
    encoder = EventEncoder(accept="text/event-stream")

    async def scenario() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        _ = [_decode(item) async for item in adapter.stream(_input(), encoder)]
        follow_up = [
            _decode(item)
            async for item in adapter.stream(_follow_up_input(), encoder)
        ]
        replay = [
            _decode(item)
            async for item in adapter.stream(_follow_up_input(), encoder)
        ]
        return follow_up, replay

    follow_up, replay = asyncio.run(scenario())

    counteranalysis_delta = next(
        event
        for event in follow_up
        if event["type"] == "STATE_DELTA"
        and any(
            operation["path"] == "/recommendationChallenge"
            for operation in event["delta"]
        )
    )
    challenge = next(
        operation["value"]
        for operation in counteranalysis_delta["delta"]
        if operation["path"] == "/recommendationChallenge"
    )
    assert challenge["currentRecommendation"] == "PostgreSQL"
    assert challenge["strongestAlternative"] == "MongoDB"
    assert len(orchestrator.challenge_requests) == 1
    assert orchestrator.challenge_requests[0].mode == "challenge_current_recommendation"
    assert [event["type"] for event in replay] == ["RUN_STARTED", "RUN_ERROR"]
    assert replay[-1]["code"] == "duplicate_action"
    with database.transaction() as repositories:
        session = repositories.sessions.require("coordinator-run-71")
        run = repositories.runs.get("follow-up-run-71")
        challenges = repositories.artifacts.list_recommendation_challenges(
            "coordinator-run-71"
        )
    assert session.last_run_id == "follow-up-run-71"
    assert session.ag_ui_thread_id == "browser-thread-71"
    assert run is not None and run.status == "completed"
    assert len(challenges) == 1


@pytest.mark.parametrize(
    ("action_type", "payload", "expected_criteria"),
    [
        (
            "research_deeper",
            {"focusAreas": ["Schema flexibility"], "desiredDepth": "deep"},
            ["Schema flexibility"],
        ),
        (
            "focus_on_criterion",
            {"criterion": "Data integrity"},
            ["Data integrity"],
        ),
    ],
)
def test_research_follow_ups_rerun_specialists_in_the_same_session(
    database: Database,
    action_type: str,
    payload: dict[str, Any],
    expected_criteria: list[str],
) -> None:
    planner = RecordingPlanner()
    orchestrator = BlockingOrchestrator()
    orchestrator.release.set()
    adapter = CoordinatorRunAdapter(
        executor=OrchestrationCommandExecutor(
            planner=planner,
            orchestrator=orchestrator,
            persistence=WorkflowPersistenceService(database),
            projector=DurableAgUiProjector(database),
            clock=AdvancingClock(),
        )
    )
    follow_up_input = _research_follow_up_input(
        run_id=f"{action_type}-run-74",
        action_id=f"{action_type}-action-74",
        action_type=action_type,
        payload=payload,
    )
    encoder = EventEncoder(accept="text/event-stream")

    async def scenario() -> list[dict[str, Any]]:
        _ = [_decode(item) async for item in adapter.stream(_input(), encoder)]
        return [
            _decode(item)
            async for item in adapter.stream(follow_up_input, encoder)
        ]

    events = asyncio.run(scenario())

    assert events[-1]["type"] == "RUN_FINISHED"
    assert planner.requests[-1].criteria == expected_criteria
    assert planner.requests[-1].desired_depth == "deep"
    assert orchestrator.execute_calls == 2
    with database.transaction() as repositories:
        session = repositories.sessions.require("coordinator-run-71")
        run = repositories.runs.get(f"{action_type}-run-74")
        tasks = repositories.agent_tasks.list_by_session("coordinator-run-71")
        analyses = repositories.artifacts.list_analysis("coordinator-run-71")
    assert session.ag_ui_thread_id == "browser-thread-71"
    assert session.last_run_id == f"{action_type}-run-74"
    assert run is not None and run.status == "completed"
    assert len(tasks) == 5
    assert len(analyses) == 2
