"""Bounded A2UI compiler, validation, and deterministic fixture tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from agents.coordinator.a2ui import (
    ALLOWED_COMPONENTS,
    A2uiCompilationError,
    compile_intake_surface,
    validate_intake_surface,
)
from packages.contracts import A2UI_CATALOG_ID, A2uiSurface
from packages.testing import load_intake_fixture

FIXTURE_IDS = (
    "technology-database",
    "procurement-design-laptop",
    "travel-team-offsite",
)


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_golden_proposals_compile_to_complete_valid_surfaces(fixture_id: str) -> None:
    fixture = load_intake_fixture(fixture_id)

    surface = compile_intake_surface(fixture.response.session_id, fixture.artifact.payload)

    assert surface.protocol_version == "0.9.1"
    assert surface.catalog_id == A2UI_CATALOG_ID
    assert [next(key for key in message if key != "version") for message in surface.messages] == [
        "createSurface",
        "updateDataModel",
        "updateComponents",
    ]
    components = surface.messages[2]["updateComponents"]["components"]
    data_model = surface.messages[1]["updateDataModel"]["value"]
    assert {component["component"] for component in components} <= ALLOWED_COMPONENTS
    assert components[-1]["id"] == "root"
    assert data_model["requiredFieldIds"] == [
        field.field_id for field in fixture.artifact.payload.fields if field.required
    ]
    assert validate_intake_surface(surface) == surface


def test_compiler_is_deterministic_and_domains_materially_change_the_form() -> None:
    surfaces = [
        compile_intake_surface(
            load_intake_fixture(fixture_id).response.session_id,
            load_intake_fixture(fixture_id).artifact.payload,
        )
        for fixture_id in FIXTURE_IDS
    ]

    assert (
        compile_intake_surface(
            load_intake_fixture(FIXTURE_IDS[0]).response.session_id,
            load_intake_fixture(FIXTURE_IDS[0]).artifact.payload,
        ).to_ag_ui()
        == surfaces[0].to_ag_ui()
    )
    field_signatures = [
        tuple(
            (component["component"], component.get("label"))
            for component in surface.messages[2]["updateComponents"]["components"]
            if component["component"] in {"TextField", "ChoicePicker", "CheckBox"}
        )
        for surface in surfaces
    ]
    assert len(set(field_signatures)) == len(FIXTURE_IDS)


def test_invalid_proposal_fails_before_messages_are_created() -> None:
    fixture = load_intake_fixture("technology-database")
    invalid = fixture.artifact.payload.model_copy(update={"fields": []})

    with pytest.raises(A2uiCompilationError, match="proposal is invalid"):
        compile_intake_surface(fixture.response.session_id, invalid)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_component",
        "unknown_action",
        "unknown_binding",
        "dynamic_label",
        "unsafe_property",
        "orphan",
        "cycle",
    ],
)
def test_catalog_action_binding_and_reachability_mutations_fail_closed(mutation: str) -> None:
    fixture = load_intake_fixture("technology-database")
    original = compile_intake_surface(fixture.response.session_id, fixture.artifact.payload)
    payload = deepcopy(original.to_ag_ui())
    components = payload["messages"][2]["updateComponents"]["components"]

    if mutation == "unknown_component":
        components[0]["component"] = "RemoteHtml"
    elif mutation == "unknown_action":
        next(item for item in components if item["id"] == "submit-intake")["action"]["event"][
            "name"
        ] = "open_url"
    elif mutation == "unknown_binding":
        next(item for item in components if item["id"].startswith("field-"))["value"] = {
            "path": "/credentials/token"
        }
    elif mutation == "dynamic_label":
        next(item for item in components if item["id"].startswith("field-"))["label"] = {
            "path": "/credentials/token"
        }
    elif mutation == "unsafe_property":
        components[0]["style"] = "position: fixed"
    elif mutation == "orphan":
        components[-1]["children"].remove("intake-summary")
    else:
        components[-1]["children"] = ["root"]

    with pytest.raises(A2uiCompilationError):
        validate_intake_surface(payload)


def test_oversized_or_deep_surface_payloads_fail_closed() -> None:
    fixture = load_intake_fixture("technology-database")
    original = compile_intake_surface(fixture.response.session_id, fixture.artifact.payload)
    oversized = deepcopy(original.to_ag_ui())
    oversized["messages"][2]["updateComponents"]["components"][0]["text"] = "x" * (128 * 1024)

    with pytest.raises(ValueError, match="exceeds the allowed size"):
        A2uiSurface.model_validate(oversized)

    deep = deepcopy(original.to_ag_ui())
    event = next(
        item
        for item in deep["messages"][2]["updateComponents"]["components"]
        if item["id"] == "submit-intake"
    )["action"]["event"]
    nested: dict[str, object] = {}
    cursor = nested
    for _ in range(14):
        child: dict[str, object] = {}
        cursor["nested"] = child
        cursor = child
    event["context"]["nested"] = nested

    with pytest.raises(A2uiCompilationError):
        validate_intake_surface(deep)


def test_surface_creation_and_answer_values_are_closed() -> None:
    fixture = load_intake_fixture("technology-database")
    original = compile_intake_surface(fixture.response.session_id, fixture.artifact.payload)
    remote_data_model = deepcopy(original.to_ag_ui())
    remote_data_model["messages"][0]["createSurface"]["sendDataModel"] = True

    with pytest.raises(A2uiCompilationError):
        validate_intake_surface(remote_data_model)

    nested_answer = deepcopy(original.to_ag_ui())
    answers = nested_answer["messages"][1]["updateDataModel"]["value"]["answers"]
    answers[next(iter(answers))] = {"secret": "value"}

    with pytest.raises(A2uiCompilationError):
        validate_intake_surface(nested_answer)
