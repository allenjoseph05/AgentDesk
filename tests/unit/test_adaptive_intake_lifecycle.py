"""Coordinator adaptive-intake lifecycle, compilation, and persistence tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import TransportProtocol
from sqlalchemy.pool import StaticPool

from agents.coordinator.a2a_client import RemoteTaskResult
from agents.coordinator.a2ui import DurableA2uiProjector
from agents.coordinator.intake import (
    IntakeCompilationError,
    compile_research_request,
    direct_research_request,
    request_is_complete,
)
from agents.coordinator.intake_execution import AdaptiveIntakeCommandExecutor
from agents.coordinator.persistence import WorkflowPersistenceService
from agents.coordinator.projection import DurableAgUiProjector
from agents.coordinator.registry import RegisteredAgent
from agents.coordinator.run_adapter import (
    CoordinatorCommand,
    CoordinatorRunOutcome,
    PrepareResearchCommand,
    RunCorrelation,
    SkipIntakeCommand,
    StartResearchCommand,
    SubmitIntakeCommand,
)
from packages.contracts import (
    AgentDeskAction,
    ArtifactEnvelope,
    IntakeResponse,
    ScopeProposal,
    ScopeProposalArtifact,
    ScopingRequest,
)
from packages.persistence import Database, metadata
from packages.testing import load_intake_fixture


class AdvancingClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


@pytest.fixture
def database() -> Iterator[Database]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    metadata.create_all(engine)
    database = Database(engine)
    try:
        yield database
    finally:
        database.dispose()


def _agent() -> RegisteredAgent:
    return RegisteredAgent(
        agent_id="scoper",
        base_url="http://scoper.test",
        card=AgentCard(
            name="Test decision scoper",
            description="Fixture scoper.",
            supported_interfaces=[
                AgentInterface(
                    url="http://scoper.test",
                    protocol_binding=TransportProtocol.HTTP_JSON,
                    protocol_version="1.0",
                )
            ],
            version="1.0",
            capabilities=AgentCapabilities(streaming=True),
            default_input_modes=["application/json"],
            default_output_modes=["application/json"],
            skills=[
                AgentSkill(
                    id="decision-scoping",
                    name="Decision scoping",
                    description="Scope one decision.",
                    tags=["intake"],
                )
            ],
        ),
    )


class FakeRegistry:
    def __init__(self, agent: RegisteredAgent | None = None) -> None:
        self.agent = agent

    def first_by_skill(self, skill: str) -> RegisteredAgent | None:
        return self.agent if skill == "decision-scoping" else None


class FixtureRemoteClient:
    def __init__(self, artifact: ScopeProposalArtifact) -> None:
        self.artifact = artifact
        self.requests: list[ScopingRequest] = []
        self.cancelled: list[str] = []

    async def execute(
        self,
        *,
        agent: RegisteredAgent,
        request: ScopingRequest,
        artifact_name: str,
        payload_model: type[ScopeProposal],
        timeout_seconds: float,
        on_task_started: Any = None,
    ) -> RemoteTaskResult[ScopeProposal]:
        del artifact_name, payload_model, timeout_seconds
        self.requests.append(request)
        task_id = self.artifact.provenance.remote_task_id
        if on_task_started is not None:
            await on_task_started(task_id)
        return RemoteTaskResult(
            agent_id=agent.agent_id,
            remote_task_id=task_id,
            remote_context_id="scope-context-1",
            artifact=ArtifactEnvelope[ScopeProposal].model_validate(
                self.artifact.model_dump(mode="python")
            ),
        )

    async def cancel(
        self,
        *,
        agent: RegisteredAgent,
        remote_task_id: str,
        timeout_seconds: float,
    ) -> None:
        del agent, timeout_seconds
        self.cancelled.append(remote_task_id)


class BlockingRemoteClient(FixtureRemoteClient):
    def __init__(self, artifact: ScopeProposalArtifact) -> None:
        super().__init__(artifact)
        self.started = asyncio.Event()

    async def execute(
        self,
        *,
        agent: RegisteredAgent,
        request: ScopingRequest,
        artifact_name: str,
        payload_model: type[ScopeProposal],
        timeout_seconds: float,
        on_task_started: Any = None,
    ) -> RemoteTaskResult[ScopeProposal]:
        del artifact_name, payload_model, timeout_seconds
        self.requests.append(request)
        task_id = self.artifact.provenance.remote_task_id
        if on_task_started is not None:
            await on_task_started(task_id)
        self.started.set()
        await asyncio.Future()
        raise AssertionError("blocking remote should be cancelled")


class RecordingDownstream:
    def __init__(self) -> None:
        self.commands: list[CoordinatorCommand] = []

    async def execute(self, command: CoordinatorCommand) -> AsyncIterator[Any]:
        self.commands.append(command)
        yield CoordinatorRunOutcome(status="completed", message="Accepted.")


def _correlation(
    *,
    run_id: str,
    action_id: str,
    session_id: str = "intake-session",
    thread_id: str = "intake-thread",
    principal_id: str = "user-1",
) -> RunCorrelation:
    return RunCorrelation(
        thread_id=thread_id,
        run_id=run_id,
        action_id=action_id,
        session_id=session_id,
        principal_id=principal_id,
    )


def _executor(
    database: Database,
    fixture_id: str = "technology-database",
) -> tuple[
    AdaptiveIntakeCommandExecutor,
    RecordingDownstream,
    FixtureRemoteClient,
    AdvancingClock,
]:
    fixture = load_intake_fixture(fixture_id)
    clock = AdvancingClock()
    persistence = WorkflowPersistenceService(database)
    downstream = RecordingDownstream()
    remote = FixtureRemoteClient(fixture.artifact)
    executor = AdaptiveIntakeCommandExecutor(
        downstream=downstream,
        registry=FakeRegistry(_agent()),  # type: ignore[arg-type]
        persistence=persistence,
        projector=DurableAgUiProjector(database),
        remote_client=remote,
        clock=clock,
    )
    return executor, downstream, remote, clock


@pytest.mark.parametrize(
    "fixture_id",
    ["technology-database", "procurement-design-laptop", "travel-team-offsite"],
)
def test_compiler_reconstructs_all_golden_research_requests(fixture_id: str) -> None:
    fixture = load_intake_fixture(fixture_id)
    request = ScopingRequest(question=fixture.artifact.payload.question)

    compiled = compile_research_request(request, fixture.artifact.payload, fixture.response)

    assert compiled == fixture.expected_request


def test_completeness_bypass_is_deterministic() -> None:
    incomplete = ScopingRequest(question="A or B?")
    complete = ScopingRequest(
        question="A or B?",
        options=["A", "B"],
        criteria=["Cost"],
        desired_depth="fast",
    )

    assert not request_is_complete(incomplete)
    assert request_is_complete(complete)
    assert direct_research_request(complete).options == ["A", "B"]
    with pytest.raises(IntakeCompilationError):
        direct_research_request(incomplete)


def test_new_agui_actions_are_strict_and_versioned() -> None:
    fixture = load_intake_fixture("technology-database")
    prepare = AgentDeskAction.model_validate(
        {
            "type": "prepare_research",
            "actionId": "prepare-1",
            "sessionId": None,
            "payload": {"question": fixture.artifact.payload.question},
        }
    )
    submit = AgentDeskAction.model_validate(
        {
            "type": "submit_intake",
            "actionId": "submit-1",
            "sessionId": fixture.response.session_id,
            "payload": {"response": fixture.response.model_dump(mode="json")},
        }
    )

    assert prepare.to_ag_ui()["type"] == "prepare_research"
    assert submit.to_ag_ui()["payload"]["response"]["proposalId"] == (fixture.response.proposal_id)
    assert "workload_profile" in submit.to_ag_ui()["payload"]["response"]["answers"]
    assert AgentDeskAction.model_validate(submit.to_ag_ui()) == submit
    with pytest.raises(ValueError):
        AgentDeskAction.model_validate(
            {
                "type": "skip_intake",
                "actionId": "skip-1",
                "sessionId": "session-1",
                "payload": {"unsafe": True},
            }
        )


def test_prepare_persists_proposal_before_projecting_awaiting_input(
    database: Database,
) -> None:
    fixture = load_intake_fixture("technology-database")
    executor, downstream, remote, _ = _executor(database)
    command = PrepareResearchCommand(
        correlation=_correlation(run_id="prepare-run", action_id="prepare-action"),
        request=ScopingRequest(question=fixture.artifact.payload.question),
        user_message=fixture.artifact.payload.question,
    )

    updates = asyncio.run(_collect(executor.execute(command)))

    assert downstream.commands == []
    assert remote.requests == [command.request]
    with database.transaction() as repositories:
        session = repositories.sessions.require("intake-session")
        proposal = repositories.intake.get_proposal_by_session("intake-session")
        transitions = repositories.transitions.list_by_session("intake-session")
    assert session.status == "awaiting_input"
    assert proposal is not None
    assert proposal.artifact == fixture.artifact
    assert [item.to_status for item in transitions] == ["scoping", "awaiting_input"]
    assert updates[-3].snapshot.status == "awaiting_input"
    assert updates[-3].snapshot.available_actions == ["submit_intake", "skip_intake"]
    assert updates[-2].surface.proposal_id == fixture.artifact.payload.proposal_id
    assert DurableA2uiProjector(database).surface("intake-session") == updates[-2].surface
    assert "messages" not in proposal.model_dump(mode="json")
    assert updates[-1].status == "completed"


def test_submit_persists_response_and_resumes_same_session(database: Database) -> None:
    fixture = load_intake_fixture("technology-database")
    executor, downstream, _, _ = _executor(database)
    prepare = PrepareResearchCommand(
        correlation=_correlation(run_id="prepare-run", action_id="prepare-action"),
        request=ScopingRequest(question=fixture.artifact.payload.question),
        user_message=fixture.artifact.payload.question,
    )
    asyncio.run(_collect(executor.execute(prepare)))
    response = IntakeResponse.model_validate(
        fixture.response.model_copy(update={"session_id": "intake-session"}).model_dump()
    )
    submit = SubmitIntakeCommand(
        correlation=_correlation(run_id="submit-run", action_id="submit-action"),
        response=response,
        user_message="Submitted clarification answers.",
    )

    asyncio.run(_collect(executor.execute(submit)))

    resumed = downstream.commands[-1]
    assert isinstance(resumed, StartResearchCommand)
    assert resumed.correlation.session_id == "intake-session"
    assert resumed.resume_session and resumed.run_initialized
    assert resumed.request == fixture.expected_request
    with database.transaction() as repositories:
        proposal = repositories.intake.get_proposal_by_session("intake-session")
        saved = repositories.intake.get_response_by_action("submit-action")
    assert proposal is not None and proposal.status == "accepted"
    assert saved is not None and saved.normalized_request == fixture.expected_request
    with pytest.raises(ValueError, match="No active intake proposal"):
        DurableA2uiProjector(database).surface("intake-session")


def test_skip_uses_trusted_defaults_and_direct_complete_request_bypasses_scoper(
    database: Database,
) -> None:
    fixture = load_intake_fixture("technology-database")
    executor, downstream, remote, _ = _executor(database)
    prepare = PrepareResearchCommand(
        correlation=_correlation(run_id="prepare-run", action_id="prepare-action"),
        request=ScopingRequest(question=fixture.artifact.payload.question),
        user_message=fixture.artifact.payload.question,
    )
    asyncio.run(_collect(executor.execute(prepare)))
    asyncio.run(
        _collect(
            executor.execute(
                SkipIntakeCommand(
                    correlation=_correlation(run_id="skip-run", action_id="skip-action"),
                    user_message="Skip clarification.",
                )
            )
        )
    )
    skipped = downstream.commands[-1]
    assert isinstance(skipped, StartResearchCommand)
    assert skipped.request.options == fixture.artifact.payload.suggested_options

    complete = PrepareResearchCommand(
        correlation=_correlation(
            run_id="direct-run",
            action_id="direct-action",
            session_id="direct-session",
        ),
        request=ScopingRequest(
            question="A or B?",
            options=["A", "B"],
            criteria=["Cost"],
        ),
        user_message="A or B?",
    )
    asyncio.run(_collect(executor.execute(complete)))
    direct = downstream.commands[-1]
    assert isinstance(direct, StartResearchCommand)
    assert not direct.resume_session
    assert direct.action_type == "prepare_research"
    assert len(remote.requests) == 1


def test_cross_session_or_stale_response_fails_without_overwriting_proposal(
    database: Database,
) -> None:
    fixture = load_intake_fixture("technology-database")
    executor, downstream, _, _ = _executor(database)
    prepare = PrepareResearchCommand(
        correlation=_correlation(run_id="prepare-run", action_id="prepare-action"),
        request=ScopingRequest(question=fixture.artifact.payload.question),
        user_message=fixture.artifact.payload.question,
    )
    asyncio.run(_collect(executor.execute(prepare)))
    wrong = IntakeResponse.model_validate(
        fixture.response.model_copy(update={"session_id": "another-session"}).model_dump()
    )
    updates = asyncio.run(
        _collect(
            executor.execute(
                SubmitIntakeCommand(
                    correlation=_correlation(run_id="submit-run", action_id="submit-action"),
                    response=wrong,
                    user_message="Submitted clarification answers.",
                )
            )
        )
    )

    assert updates[-1].status == "failed"
    assert updates[-1].error_code == "invalid_intake_response"
    assert downstream.commands == []
    with database.transaction() as repositories:
        proposal = repositories.intake.get_proposal_by_session("intake-session")
    assert proposal is not None and proposal.status == "awaiting_response"


def test_browser_cancellation_reaches_active_scoper_and_commits_no_proposal(
    database: Database,
) -> None:
    fixture = load_intake_fixture("technology-database")
    clock = AdvancingClock()
    persistence = WorkflowPersistenceService(database)
    remote = BlockingRemoteClient(fixture.artifact)
    executor = AdaptiveIntakeCommandExecutor(
        downstream=RecordingDownstream(),
        registry=FakeRegistry(_agent()),  # type: ignore[arg-type]
        persistence=persistence,
        projector=DurableAgUiProjector(database),
        remote_client=remote,
        clock=clock,
    )
    command = PrepareResearchCommand(
        correlation=_correlation(run_id="prepare-run", action_id="prepare-action"),
        request=ScopingRequest(question=fixture.artifact.payload.question),
        user_message=fixture.artifact.payload.question,
    )

    async def cancel() -> None:
        execution = asyncio.create_task(_collect(executor.execute(command)))
        await remote.started.wait()
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution

    asyncio.run(cancel())

    assert remote.cancelled == [fixture.artifact.provenance.remote_task_id]
    with database.transaction() as repositories:
        session = repositories.sessions.require("intake-session")
        proposal = repositories.intake.get_proposal_by_session("intake-session")
    assert session.status == "cancelled"
    assert proposal is None


async def _collect(updates: AsyncIterator[Any]) -> list[Any]:
    return [update async for update in updates]
