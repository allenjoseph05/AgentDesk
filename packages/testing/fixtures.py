"""Strict loaders for shared backend/frontend JSON fixture scenarios."""

import json
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from packages.contracts import (
    DecisionAnalysis,
    EvidenceBundle,
    ResearchRequest,
    VerificationReport,
)
from packages.contracts.base import ContractModel, NonEmptyText

FixtureKind = Literal["good", "partial", "contradictory", "failure"]
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "research"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"


class FixtureFailure(ContractModel):
    code: NonEmptyText
    message: NonEmptyText
    retryable: bool


class FixtureManifestEntry(ContractModel):
    fixture_id: NonEmptyText
    kind: FixtureKind
    file: NonEmptyText
    golden: bool = False


class ResearchFixture(ContractModel):
    fixture_id: NonEmptyText
    kind: FixtureKind
    golden: bool = False
    request: ResearchRequest
    evidence_bundle: EvidenceBundle | None = None
    decision_analysis: DecisionAnalysis | None = None
    verification_report: VerificationReport | None = None
    failure: FixtureFailure | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ResearchFixture":
        if self.kind == "failure":
            if self.failure is None or self.evidence_bundle is not None:
                raise ValueError("Failure fixtures require only a failure outcome.")
        elif self.evidence_bundle is None or self.failure is not None:
            raise ValueError("Successful fixtures require an evidence bundle and no failure.")
        if self.golden and self.kind != "good":
            raise ValueError("Only a good fixture may be marked golden.")
        return self


def list_research_fixtures() -> list[FixtureManifestEntry]:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [FixtureManifestEntry.model_validate(entry) for entry in raw["fixtures"]]


def load_research_fixture(fixture_id: str) -> ResearchFixture:
    entries = {entry.fixture_id: entry for entry in list_research_fixtures()}
    try:
        entry = entries[fixture_id]
    except KeyError as error:
        raise KeyError(f"Unknown research fixture: {fixture_id}") from error
    fixture_path = (FIXTURE_ROOT / entry.file).resolve()
    if fixture_path.parent != FIXTURE_ROOT.resolve():
        raise ValueError("Fixture manifest path escapes the shared fixture directory.")
    fixture = ResearchFixture.model_validate_json(fixture_path.read_text(encoding="utf-8"))
    if (fixture.fixture_id, fixture.kind, fixture.golden) != (
        entry.fixture_id,
        entry.kind,
        entry.golden,
    ):
        raise ValueError(f"Fixture metadata does not match manifest entry: {fixture_id}")
    return fixture
