"""Strict loaders for shared adaptive-intake fixtures and malformed cases."""

from __future__ import annotations

import copy
import json
import unicodedata
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from packages.contracts import (
    IntakeResponse,
    ResearchRequest,
    ScopeProposalArtifact,
    validate_intake_response,
)
from packages.contracts.base import ContractModel, NonEmptyText

IntakeDomain = Literal["technology", "procurement", "travel"]
MutationKind = Literal["add", "remove", "replace"]
MutationTarget = Literal["artifact", "response"]
INTAKE_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "intake"
INTAKE_MANIFEST_PATH = INTAKE_FIXTURE_ROOT / "manifest.json"
MAX_REPEAT_COUNT = 64 * 1024


class IntakeFixtureManifestEntry(ContractModel):
    fixture_id: NonEmptyText
    domain: IntakeDomain
    file: NonEmptyText


class IntakeFixture(ContractModel):
    fixture_id: NonEmptyText
    domain: IntakeDomain
    artifact: ScopeProposalArtifact
    response: IntakeResponse
    expected_request: ResearchRequest

    @model_validator(mode="after")
    def validate_linked_contracts(self) -> IntakeFixture:
        proposal = self.artifact.payload
        validate_intake_response(proposal, self.response)
        if self.expected_request.question != proposal.question:
            raise ValueError("Expected request question must match the scope proposal question.")
        if not 2 <= len(self.expected_request.options) <= 4:
            raise ValueError("Expected request must contain two to four options.")
        if not self.expected_request.criteria:
            raise ValueError("Expected request must contain at least one criterion.")
        for values, label in (
            (self.expected_request.options, "Expected options"),
            (self.expected_request.constraints, "Expected constraints"),
            (self.expected_request.criteria, "Expected criteria"),
        ):
            normalized = [
                unicodedata.normalize("NFKC", " ".join(value.split())).lower() for value in values
            ]
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"{label} must be unique after normalization.")
        return self


class RepeatValue(ContractModel):
    value: str = Field(min_length=1, max_length=8)
    count: int = Field(ge=1, le=MAX_REPEAT_COUNT)


class IntakeMutation(ContractModel):
    operation: MutationKind
    path: NonEmptyText
    value: Any = None
    repeat: RepeatValue | None = None

    @model_validator(mode="after")
    def validate_operation(self) -> IntakeMutation:
        if not self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError("Mutation paths must be absolute JSON pointers without traversal.")
        if self.repeat is not None and self.operation == "remove":
            raise ValueError("Remove mutations cannot define repeated values.")
        return self


class MalformedIntakeCase(ContractModel):
    case_id: NonEmptyText
    fixture_id: NonEmptyText
    target: MutationTarget
    operations: list[IntakeMutation] = Field(min_length=1, max_length=8)


def list_intake_fixtures() -> list[IntakeFixtureManifestEntry]:
    raw = json.loads(INTAKE_MANIFEST_PATH.read_text(encoding="utf-8"))
    return [IntakeFixtureManifestEntry.model_validate(entry) for entry in raw["fixtures"]]


def load_intake_fixture(fixture_id: str) -> IntakeFixture:
    entries = {entry.fixture_id: entry for entry in list_intake_fixtures()}
    try:
        entry = entries[fixture_id]
    except KeyError as error:
        raise KeyError(f"Unknown intake fixture: {fixture_id}") from error
    fixture_path = (INTAKE_FIXTURE_ROOT / entry.file).resolve()
    if fixture_path.parent != INTAKE_FIXTURE_ROOT.resolve():
        raise ValueError("Fixture manifest path escapes the shared intake directory.")
    fixture = IntakeFixture.model_validate_json(fixture_path.read_text(encoding="utf-8"))
    if (fixture.fixture_id, fixture.domain) != (entry.fixture_id, entry.domain):
        raise ValueError(f"Intake fixture metadata does not match its manifest: {fixture_id}")
    return fixture


def list_malformed_intake_cases() -> list[MalformedIntakeCase]:
    raw = json.loads((INTAKE_FIXTURE_ROOT / "malformed.json").read_text(encoding="utf-8"))
    return [MalformedIntakeCase.model_validate(case) for case in raw["cases"]]


def apply_intake_mutations(
    fixture: IntakeFixture,
    operations: list[IntakeMutation],
) -> dict[str, Any]:
    """Apply the corpus's small, deterministic JSON mutation vocabulary."""

    document = fixture.model_dump(mode="json")
    for mutation in operations:
        segments = [_decode_pointer(segment) for segment in mutation.path.lstrip("/").split("/")]
        if not segments:
            raise ValueError("Mutation paths must address a fixture value.")
        parent: Any = document
        for segment in segments[:-1]:
            parent = parent[int(segment)] if isinstance(parent, list) else parent[segment]
        final = segments[-1]
        value = (
            mutation.repeat.value * mutation.repeat.count
            if mutation.repeat is not None
            else copy.deepcopy(mutation.value)
        )
        if isinstance(parent, list):
            index = int(final)
            if mutation.operation == "remove":
                parent.pop(index)
            elif mutation.operation == "add":
                parent.insert(index, value)
            else:
                parent[index] = value
        elif mutation.operation == "remove":
            del parent[final]
        else:
            parent[final] = value
    return document


def _decode_pointer(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")
