"""Cross-boundary contract tests for versioned AgentDesk AG-UI data."""

import pytest
from pydantic import ValidationError

from packages.contracts import AgentDeskAction, AgentDeskViewState
from packages.testing import (
    list_ag_ui_fixtures,
    load_ag_ui_fixture,
    load_ag_ui_fixture_raw,
)

pytestmark = pytest.mark.agui_contract


def test_manifest_covers_all_required_ag_ui_scenarios() -> None:
    entries = list_ag_ui_fixtures()

    assert {entry.kind for entry in entries} == {
        "good",
        "partial",
        "contradictory",
        "failure",
        "malformed",
    }
    assert sum(entry.valid for entry in entries) == 4


@pytest.mark.parametrize(
    "fixture_id",
    [
        "postgresql-vs-mongodb-golden",
        "postgresql-vs-mongodb-partial",
        "postgresql-vs-mongodb-contradictory",
        "postgresql-vs-mongodb-failure",
    ],
)
def test_valid_fixtures_round_trip_through_python_contracts(fixture_id: str) -> None:
    raw = load_ag_ui_fixture_raw(fixture_id)
    fixture = load_ag_ui_fixture(fixture_id)

    assert fixture.action.to_ag_ui() == raw["action"]
    assert fixture.state.to_ag_ui() == raw["state"]


def test_malformed_fixture_fails_action_and_state_contracts() -> None:
    raw = load_ag_ui_fixture_raw("malformed-version-and-count")

    with pytest.raises(ValidationError):
        AgentDeskAction.model_validate(raw["action"])
    with pytest.raises(ValidationError):
        AgentDeskViewState.model_validate(raw["state"])
    with pytest.raises(ValueError, match="malformed by design"):
        load_ag_ui_fixture("malformed-version-and-count")


@pytest.mark.parametrize(
    ("action_type", "payload"),
    [
        ("challenge_recommendation", {"challenge": "Argue the strongest opposing case."}),
        ("research_deeper", {"focusAreas": ["Cost"], "desiredDepth": "deep"}),
        ("focus_on_criterion", {"criterion": "Operational complexity"}),
        ("retry_failed_agent", {"agentId": "research-agent", "remoteTaskId": None}),
    ],
)
def test_follow_up_actions_require_session_and_round_trip(
    action_type: str, payload: dict[str, object]
) -> None:
    raw = {
        "schemaVersion": "1.0",
        "actionId": f"action-{action_type}",
        "type": action_type,
        "sessionId": "session-1",
        "payload": payload,
    }

    action = AgentDeskAction.model_validate(raw)

    assert action.to_ag_ui() == raw
    without_session = {**raw, "sessionId": None}
    with pytest.raises(ValidationError):
        AgentDeskAction.model_validate(without_session)


def test_state_rejects_broken_evidence_references_and_counts() -> None:
    raw = load_ag_ui_fixture_raw("postgresql-vs-mongodb-partial")["state"]

    with pytest.raises(ValidationError, match="evidenceCount"):
        AgentDeskViewState.model_validate({**raw, "evidenceCount": 0})
    broken_claims = [{**raw["claims"][0], "evidenceIds": ["missing-evidence"]}]
    with pytest.raises(ValidationError, match="unknown evidence"):
        AgentDeskViewState.model_validate({**raw, "claims": broken_claims})
