"""Strict loaders for shared AG-UI state/action fixtures."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field

from packages.contracts import AgentDeskAction, AgentDeskViewState
from packages.contracts.base import ContractModel, NonEmptyText

AgUiFixtureKind = Literal["good", "partial", "contradictory", "failure", "malformed"]
AG_UI_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "agui"
AG_UI_MANIFEST_PATH = AG_UI_FIXTURE_ROOT / "manifest.json"


class AgUiFixtureManifestEntry(ContractModel):
    fixture_id: NonEmptyText = Field(
        validation_alias=AliasChoices("fixtureId", "fixture_id"),
        serialization_alias="fixtureId",
    )
    kind: AgUiFixtureKind
    file: NonEmptyText
    valid: bool


class AgUiFixture(ContractModel):
    fixture_id: NonEmptyText = Field(
        validation_alias=AliasChoices("fixtureId", "fixture_id"),
        serialization_alias="fixtureId",
    )
    kind: Literal["good", "partial", "contradictory", "failure"]
    valid: Literal[True]
    action: AgentDeskAction
    state: AgentDeskViewState


def list_ag_ui_fixtures() -> list[AgUiFixtureManifestEntry]:
    raw = json.loads(AG_UI_MANIFEST_PATH.read_text(encoding="utf-8"))
    return [AgUiFixtureManifestEntry.model_validate(entry) for entry in raw["fixtures"]]


def load_ag_ui_fixture_raw(fixture_id: str) -> dict[str, Any]:
    entries = {entry.fixture_id: entry for entry in list_ag_ui_fixtures()}
    try:
        entry = entries[fixture_id]
    except KeyError as error:
        raise KeyError(f"Unknown AG-UI fixture: {fixture_id}") from error
    fixture_path = (AG_UI_FIXTURE_ROOT / entry.file).resolve()
    if fixture_path.parent != AG_UI_FIXTURE_ROOT.resolve():
        raise ValueError("AG-UI fixture manifest path escapes the shared fixture directory.")
    raw: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
    if (raw.get("fixtureId"), raw.get("kind"), raw.get("valid")) != (
        entry.fixture_id,
        entry.kind,
        entry.valid,
    ):
        raise ValueError(f"AG-UI fixture metadata does not match manifest entry: {fixture_id}")
    return raw


def load_ag_ui_fixture(fixture_id: str) -> AgUiFixture:
    raw = load_ag_ui_fixture_raw(fixture_id)
    if raw["valid"] is not True:
        raise ValueError(f"AG-UI fixture is malformed by design: {fixture_id}")
    return AgUiFixture.model_validate(raw)
