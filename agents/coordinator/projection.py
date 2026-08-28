"""Project committed Coordinator domain state into typed AG-UI events."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from ag_ui.core import StateDeltaEvent, StateSnapshotEvent

from agents.coordinator.agui_security import (
    AgUiBoundaryError,
    require_patch_size,
    require_state_size,
)
from packages.contracts import AgentDeskViewState, SpecialistView, VerificationReport
from packages.contracts.agui import FollowUpActionType, SessionStatus, SpecialistStatus
from packages.persistence import Database, WorkflowTransitionRecord
from packages.persistence.records import AgentTaskRecord, SessionPersistenceStatus


class ProjectionError(RuntimeError):
    """Persisted state cannot be safely projected to the browser."""


class AgUiEventProjection:
    """Track one frontend baseline and emit monotonic RFC 6902 deltas."""

    def __init__(self, baseline: AgentDeskViewState) -> None:
        self._state = baseline.model_copy(deep=True)
        self._last_sequence = 0

    @property
    def state(self) -> AgentDeskViewState:
        return self._state.model_copy(deep=True)

    @property
    def last_sequence(self) -> int:
        return self._last_sequence

    def snapshot_event(self) -> StateSnapshotEvent:
        snapshot = self._state.to_ag_ui()
        _validate_state_size(snapshot)
        return StateSnapshotEvent(snapshot=snapshot)

    def project(
        self,
        target: AgentDeskViewState,
        *,
        sequence: int | None = None,
    ) -> StateDeltaEvent | None:
        candidate = AgentDeskViewState.model_validate(target.model_dump(mode="python"))
        if candidate.session_id != self._state.session_id:
            raise ProjectionError("AG-UI projection cannot change Coordinator session identity.")
        if sequence is not None:
            if sequence < 1:
                raise ProjectionError("AG-UI update sequence must be positive.")
            if sequence <= self._last_sequence:
                return None

        delta = state_delta(self._state, candidate)
        self._state = candidate.model_copy(deep=True)
        if sequence is not None:
            self._last_sequence = sequence
        return StateDeltaEvent(delta=delta) if delta else None


class DurableAgUiProjector:
    """Rebuild renderable state exclusively from persisted domain records."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def snapshot(self, session_id: str) -> AgentDeskViewState:
        with self._database.transaction() as repositories:
            session = repositories.sessions.require(session_id)
            tasks = repositories.agent_tasks.list_by_session(session_id)
            evidence = repositories.artifacts.list_evidence(session_id)
            claims = repositories.artifacts.list_claims(session_id)
            research_artifacts = repositories.artifacts.list_research_artifacts(session_id)
            analyses = repositories.artifacts.list_analysis(session_id)
            challenges = repositories.artifacts.list_recommendation_challenges(session_id)
            verification_reports = repositories.artifacts.list_verification_reports(session_id)

        agents = _latest_agent_views(tasks)
        failed_agents = [agent for agent in agents if agent.status == "failed"]
        status = _session_status(session.status)
        warnings = (
            ["One or more specialist tasks did not complete."]
            if status == "partial" or (failed_agents and status != "failed")
            else []
        )
        for record in research_artifacts:
            warnings.extend(
                f"Evidence gap: {unknown}" for unknown in record.envelope.payload.unknowns
            )
            warnings.extend(
                f"Research note: {note}" for note in record.envelope.payload.research_notes
            )
        verification = verification_reports[-1].envelope.payload if verification_reports else None
        if verification is not None:
            warnings.extend(_verification_warnings(verification))
        warnings = list(dict.fromkeys(warnings))
        errors = ["The workflow could not be completed."] if status == "failed" else []
        return AgentDeskViewState(
            session_id=session.id,
            question=session.question,
            status=status,
            active_step=(
                session.active_step if session.status != "created" else "accept-research-request"
            ),
            agents=agents,
            evidence=[record.evidence for record in evidence],
            evidence_count=len(evidence),
            claims=[record.claim for record in claims],
            analysis=analyses[-1].analysis if analyses else None,
            recommendation_challenge=(challenges[-1].envelope.payload if challenges else None),
            verification=verification,
            warnings=warnings,
            errors=errors,
            available_actions=_available_actions(status, bool(failed_agents)),
            last_updated_at=session.updated_at,
        )

    def snapshot_event(self, session_id: str) -> StateSnapshotEvent:
        return StateSnapshotEvent(snapshot=self.snapshot(session_id).to_ag_ui())

    def transition_event(
        self,
        transition: WorkflowTransitionRecord,
        previous: AgentDeskViewState,
    ) -> StateDeltaEvent | None:
        """Project only a transition that is already committed in persistence."""
        with self._database.transaction() as repositories:
            committed = repositories.transitions.get(
                transition.session_id,
                transition.sequence,
            )
        if committed != transition:
            raise ProjectionError("Workflow transition is not durably committed.")
        target = self.snapshot(transition.session_id)
        if target.last_updated_at is None or target.last_updated_at < transition.occurred_at:
            raise ProjectionError("Durable session state predates its committed transition.")
        return AgUiEventProjection(previous).project(
            target,
            sequence=transition.sequence,
        )


def state_delta(
    previous: AgentDeskViewState,
    target: AgentDeskViewState,
) -> list[dict[str, Any]]:
    """Build deterministic top-level RFC 6902 replace operations."""
    before = previous.to_ag_ui()
    after = target.to_ag_ui()
    delta = [
        {"op": "replace", "path": f"/{_escape_pointer(key)}", "value": deepcopy(value)}
        for key, value in after.items()
        if before.get(key) != value
    ]
    _validate_patch_size(delta)
    return delta


def apply_projected_delta(
    previous: AgentDeskViewState,
    delta: list[Any],
) -> AgentDeskViewState:
    """Apply the projector's constrained RFC 6902 output and revalidate state."""
    _validate_patch_size(delta)
    document = previous.to_ag_ui()
    for operation in delta:
        if not isinstance(operation, dict) or operation.get("op") != "replace":
            raise ProjectionError("Projected deltas support replace operations only.")
        path = operation.get("path")
        if not isinstance(path, str) or not path.startswith("/") or "/" in path[1:]:
            raise ProjectionError("Projected delta path must address one state field.")
        key = _unescape_pointer(path[1:])
        if key not in document or "value" not in operation:
            raise ProjectionError("Projected delta cannot add or remove state fields.")
        document[key] = deepcopy(operation["value"])
    _validate_state_size(document)
    return AgentDeskViewState.model_validate(document)


def _validate_state_size(value: Any) -> None:
    try:
        require_state_size(value)
    except AgUiBoundaryError as error:
        raise ProjectionError(str(error)) from error


def _validate_patch_size(value: Any) -> None:
    try:
        require_patch_size(value)
    except AgUiBoundaryError as error:
        raise ProjectionError(str(error)) from error


def _latest_agent_views(tasks: tuple[AgentTaskRecord, ...]) -> list[SpecialistView]:
    latest: dict[str, AgentTaskRecord] = {}
    for task in tasks:
        latest[task.agent_id] = task
    return [
        SpecialistView(
            agent_id=task.agent_id,
            name=task.agent_id.replace("-", " ").replace("_", " ").title(),
            skill=task.skill,
            status=_specialist_status(task.status),
            remote_task_id=task.remote_task_id,
            message=(
                "Specialist task failed."
                if task.status == "failed"
                else "Specialist task was cancelled."
                if task.status == "cancelled"
                else None
            ),
        )
        for _, task in sorted(latest.items())
    ]


def _session_status(status: SessionPersistenceStatus) -> SessionStatus:
    return "planning" if status == "created" else cast(SessionStatus, status)


def _specialist_status(status: str) -> SpecialistStatus:
    if status in {"submitted", "working"}:
        return "working"
    return cast(SpecialistStatus, status)


def _available_actions(
    status: SessionStatus,
    has_failed_agent: bool,
) -> list[FollowUpActionType]:
    actions: list[FollowUpActionType] = []
    if status == "awaiting_input":
        actions.extend(["submit_intake", "skip_intake"])
    if status in {"completed", "partial"}:
        actions.extend(
            [
                "challenge_recommendation",
                "research_deeper",
                "focus_on_criterion",
            ]
        )
    if has_failed_agent and status in {"failed", "partial"}:
        actions.append("retry_failed_agent")
    return actions


def _verification_warnings(report: VerificationReport) -> list[str]:
    return [
        f"Verification contradiction for claim {result.claim_id}: {result.rationale}"
        for result in report.results
        if result.verdict == "contradicted"
    ]


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _unescape_pointer(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")
