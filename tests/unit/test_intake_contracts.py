"""Bounded adaptive-intake contract and shared-fixture tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts import (
    INTAKE_SCHEMA_VERSION,
    MAX_INTAKE_TEXT_LENGTH,
    MAX_SCOPE_FIELDS,
    IntakeResponse,
    ScopeProposalArtifact,
    parse_intake_response,
    parse_scope_proposal_artifact,
    validate_intake_response,
)
from packages.testing import (
    MalformedIntakeCase,
    apply_intake_mutations,
    list_intake_fixtures,
    list_malformed_intake_cases,
    load_intake_fixture,
)
from scripts.export_intake_evidence import IntakeContractDocument


def test_three_domain_library_loads_as_linked_strict_contracts() -> None:
    entries = list_intake_fixtures()
    fixtures = [load_intake_fixture(entry.fixture_id) for entry in entries]

    assert [(entry.fixture_id, entry.domain) for entry in entries] == [
        ("technology-database", "technology"),
        ("procurement-design-laptop", "procurement"),
        ("travel-team-offsite", "travel"),
    ]
    assert all(fixture.artifact.schema_version == INTAKE_SCHEMA_VERSION for fixture in fixtures)
    assert all(
        validate_intake_response(fixture.artifact.payload, fixture.response) == fixture.response
        for fixture in fixtures
    )
    assert {field.kind for fixture in fixtures for field in fixture.artifact.payload.fields} == {
        "short_text",
        "single_select",
        "multi_select",
        "boolean",
    }
    procurement = load_intake_fixture("procurement-design-laptop")
    assert procurement.artifact.payload.suggested_options == []
    assert procurement.artifact.payload.fields[0].destination == "option"
    assert procurement.artifact.payload.fields[0].required is True


def test_versioned_scope_artifact_round_trips_without_transport_sdk_objects() -> None:
    fixture = load_intake_fixture("technology-database")
    serialized = fixture.artifact.model_dump(mode="json")

    assert (
        serialized
        == json.loads(
            Path("fixtures/intake/technology-database.golden.json").read_text(encoding="utf-8")
        )["artifact"]
    )
    assert serialized["schema_version"] == "1.0"
    assert serialized["payload"]["schema_version"] == "1.0"
    assert set(serialized) == {"schema_version", "provenance", "payload"}


@pytest.mark.parametrize("case", list_malformed_intake_cases(), ids=lambda case: case.case_id)
def test_malformed_shared_corpus_fails_closed_in_python(case: MalformedIntakeCase) -> None:
    fixture = load_intake_fixture(case.fixture_id)
    mutated = apply_intake_mutations(fixture, case.operations)

    if case.target == "artifact":
        with pytest.raises((ValidationError, ValueError)):
            parse_scope_proposal_artifact(mutated["artifact"])
        return

    proposal = ScopeProposalArtifact.model_validate(mutated["artifact"]).payload
    with pytest.raises((ValidationError, ValueError)):
        validate_intake_response(proposal, mutated["response"])


def test_intake_response_rejects_non_json_coercions_and_bounded_text() -> None:
    fixture = load_intake_fixture("technology-database")
    response = fixture.response.model_dump(mode="json")
    response["answers"]["workload_profile"] = 1

    with pytest.raises(ValidationError):
        IntakeResponse.model_validate(response)

    proposal = fixture.artifact.model_dump(mode="json")
    proposal["payload"]["question"] = "x" * (MAX_INTAKE_TEXT_LENGTH + 1)
    with pytest.raises(ValidationError):
        ScopeProposalArtifact.model_validate(proposal)

    oversized_response = fixture.response.model_dump(mode="json")
    oversized_response["answers"] = {
        f"field_{index}": "x" * MAX_INTAKE_TEXT_LENGTH for index in range(MAX_SCOPE_FIELDS)
    }
    with pytest.raises(ValueError, match="exceeds the allowed size"):
        parse_intake_response(oversized_response)


def test_generated_json_schema_exposes_both_versioned_boundaries() -> None:
    schema = json.loads(
        Path("fixtures/intake/intake-contracts.schema.json").read_text(encoding="utf-8")
    )

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "https://agentdesk.dev/schemas/intake-contracts-1.0.json"
    assert set(schema["properties"]) == {"artifact", "response"}
    assert {"ScopeProposal", "ScopeField", "IntakeResponse"} <= set(schema["$defs"])
    generated = IntakeContractDocument.model_json_schema()
    generated.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://agentdesk.dev/schemas/intake-contracts-1.0.json",
            "title": "AgentDesk adaptive-intake artifact and response",
        }
    )
    assert schema == generated


def test_unknown_intake_fixture_is_rejected() -> None:
    with pytest.raises(KeyError, match="Unknown intake fixture"):
        load_intake_fixture("not-in-manifest")
