"""Deterministic, fail-closed ScopeProposal to A2UI 0.9.1 compilation."""

from __future__ import annotations

import json
from typing import Any

from a2ui.core.basic_catalog.components import (
    BUTTON_COMPONENT_API,
    CHECK_BOX_COMPONENT_API,
    CHOICE_PICKER_COMPONENT_API,
    COLUMN_COMPONENT_API,
    ROW_COMPONENT_API,
    TEXT_COMPONENT_API,
    TEXT_FIELD_COMPONENT_API,
)
from a2ui.core.catalog import Catalog
from a2ui.core.validating import A2uiValidator, A2uiValidatorError, CatalogSchemaValidator

from packages.contracts import (
    A2UI_CATALOG_ID,
    A2UI_SURFACE_EVENT_NAME,
    A2UI_WIRE_VERSION,
    A2uiSurface,
    ScopeField,
    ScopeProposal,
)
from packages.persistence import Database

MAX_A2UI_COMPONENTS = 32
MAX_A2UI_COMPONENT_DEPTH = 4
SUBMIT_EVENT_NAME = "agentdesk.intake.submit.v1"
SKIP_EVENT_NAME = "agentdesk.intake.skip.v1"
ALLOWED_COMPONENTS = frozenset(
    {"Text", "TextField", "ChoicePicker", "CheckBox", "Column", "Row", "Button"}
)
ALLOWED_ACTIONS = frozenset({SUBMIT_EVENT_NAME, SKIP_EVENT_NAME})
_COMPONENT_PROPERTIES = {
    "Text": frozenset({"id", "component", "text", "variant"}),
    "TextField": frozenset({"id", "component", "label", "value", "variant", "accessibility"}),
    "ChoicePicker": frozenset(
        {
            "id",
            "component",
            "label",
            "variant",
            "options",
            "value",
            "displayStyle",
            "filterable",
            "accessibility",
        }
    ),
    "CheckBox": frozenset({"id", "component", "label", "value", "accessibility"}),
    "Column": frozenset({"id", "component", "children", "justify", "align"}),
    "Row": frozenset({"id", "component", "children", "justify", "align"}),
    "Button": frozenset({"id", "component", "child", "variant", "accessibility", "action"}),
}

_CATALOG: Catalog[Any, Any] = Catalog(
    catalog_id=A2UI_CATALOG_ID,
    spec_version=A2UI_WIRE_VERSION,
    components=[
        TEXT_COMPONENT_API,
        TEXT_FIELD_COMPONENT_API,
        CHOICE_PICKER_COMPONENT_API,
        CHECK_BOX_COMPONENT_API,
        COLUMN_COMPONENT_API,
        ROW_COMPONENT_API,
        BUTTON_COMPONENT_API,
    ],
    functions=[],
)
_CATALOG_VALIDATOR = CatalogSchemaValidator(_CATALOG)
_A2UI_VALIDATOR = A2uiValidator()


class A2uiCompilationError(ValueError):
    """A proposal cannot be represented by AgentDesk's bounded intake catalog."""


def compile_intake_surface(session_id: str, proposal: ScopeProposal) -> A2uiSurface:
    """Compile a complete, deterministic surface and validate every trust boundary."""
    try:
        proposal = ScopeProposal.model_validate(proposal.model_dump(mode="python"))
    except ValueError as error:
        raise A2uiCompilationError("The intake proposal is invalid.") from error
    surface_id = "decision-intake"
    components: list[dict[str, Any]] = [
        _text("intake-title", "Clarify your decision", variant="h2"),
        _text("intake-summary", proposal.summary),
    ]
    root_children = ["intake-title", "intake-summary"]
    answers: dict[str, str | bool | list[str]] = {}

    for field in proposal.fields:
        help_id = f"help-{field.field_id}"
        input_id = f"field-{field.field_id}"
        components.append(_text(help_id, field.help_text, variant="caption"))
        components.append(_field_component(input_id, field))
        root_children.extend([help_id, input_id])
        answers[field.field_id] = _initial_answer(field)

    components.extend(
        [
            _text("submit-label", "Continue"),
            _text("skip-label", "Skip clarification"),
            {
                "id": "submit-intake",
                "component": "Button",
                "child": "submit-label",
                "variant": "primary",
                "accessibility": {"label": "Continue with these answers"},
                "action": {
                    "event": {
                        "name": SUBMIT_EVENT_NAME,
                        "context": _action_context(session_id, proposal, include_answers=True),
                    }
                },
            },
            {
                "id": "skip-intake",
                "component": "Button",
                "child": "skip-label",
                "variant": "borderless",
                "accessibility": {"label": "Skip clarification"},
                "action": {
                    "event": {
                        "name": SKIP_EVENT_NAME,
                        "context": _action_context(session_id, proposal, include_answers=False),
                    }
                },
            },
            {
                "id": "intake-actions",
                "component": "Row",
                "children": ["submit-intake", "skip-intake"],
                "justify": "start",
                "align": "center",
            },
        ]
    )
    root_children.append("intake-actions")
    components.append(
        {
            "id": "root",
            "component": "Column",
            "children": root_children,
            "justify": "start",
            "align": "stretch",
        }
    )

    messages = [
        {
            "version": A2UI_WIRE_VERSION,
            "createSurface": {
                "surfaceId": surface_id,
                "catalogId": A2UI_CATALOG_ID,
                "sendDataModel": False,
            },
        },
        {
            "version": A2UI_WIRE_VERSION,
            "updateDataModel": {
                "surfaceId": surface_id,
                "value": {
                    "answers": answers,
                    "requiredFieldIds": [
                        field.field_id for field in proposal.fields if field.required
                    ],
                    "sessionId": session_id,
                    "proposalId": proposal.proposal_id,
                    "proposalVersion": proposal.schema_version,
                },
            },
        },
        {
            "version": A2UI_WIRE_VERSION,
            "updateComponents": {
                "surfaceId": surface_id,
                "components": components,
            },
        },
    ]
    try:
        surface = A2uiSurface(
            session_id=session_id,
            proposal_id=proposal.proposal_id,
            proposal_version=proposal.schema_version,
            surface_id=surface_id,
            messages=messages,
        )
        return validate_intake_surface(surface)
    except (A2uiValidatorError, ValueError, TypeError) as error:
        raise A2uiCompilationError(
            "The intake proposal produced an invalid A2UI surface."
        ) from error


class DurableA2uiProjector:
    """Recompile a surface from the protocol-neutral persisted proposal."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def surface(self, session_id: str) -> A2uiSurface:
        with self._database.transaction() as repositories:
            session = repositories.sessions.require(session_id)
            proposal = repositories.intake.get_proposal_by_session(session_id)
        if (
            session.status != "awaiting_input"
            or proposal is None
            or proposal.status != "awaiting_response"
        ):
            raise A2uiCompilationError("No active intake proposal exists for this session.")
        return compile_intake_surface(session_id, proposal.artifact.payload)


def validate_intake_surface(surface: A2uiSurface | dict[str, Any]) -> A2uiSurface:
    """Revalidate a complete event value before it crosses the AG-UI boundary."""
    try:
        validated = (
            surface if isinstance(surface, A2uiSurface) else A2uiSurface.model_validate(surface)
        )
        _validate_messages(validated.messages, validated.surface_id)
        data = validated.messages[1]["updateDataModel"]["value"]
        expected_identity = {
            "sessionId": validated.session_id,
            "proposalId": validated.proposal_id,
            "proposalVersion": validated.proposal_version,
        }
        if not isinstance(data, dict) or set(data) != {
            "answers",
            "requiredFieldIds",
            *expected_identity,
        }:
            raise ValueError("A2UI data model has an unsupported shape.")
        if any(data[key] != value for key, value in expected_identity.items()):
            raise ValueError("A2UI event metadata does not match its data model.")
        if not isinstance(data["answers"], dict):
            raise ValueError("A2UI answers must be an object.")
        if any(not isinstance(key, str) for key in data["answers"]):
            raise ValueError("A2UI answer identifiers must be strings.")
        if len(data["answers"]) > 8 or any(
            not _valid_answer_value(value) for value in data["answers"].values()
        ):
            raise ValueError("A2UI answer values are invalid.")
        required = data["requiredFieldIds"]
        if (
            not isinstance(required, list)
            or any(not isinstance(field_id, str) for field_id in required)
            or len(required) != len(set(required))
            or not set(required) <= set(data["answers"])
        ):
            raise ValueError("A2UI required field identifiers are invalid.")
        create = validated.messages[0]["createSurface"]
        if create.get("catalogId") != validated.catalog_id:
            raise ValueError("A2UI event metadata does not match its catalog.")
        _validate_bindings_and_actions(
            validated.messages[2]["updateComponents"]["components"],
            answers=set(data["answers"]),
            identity=expected_identity,
        )
        return validated
    except (A2uiValidatorError, ValueError, TypeError, KeyError) as error:
        raise A2uiCompilationError("The A2UI intake surface is invalid.") from error


def _text(component_id: str, value: str, *, variant: str = "body") -> dict[str, Any]:
    return {"id": component_id, "component": "Text", "text": value, "variant": variant}


def _field_component(component_id: str, field: ScopeField) -> dict[str, Any]:
    binding = {"path": f"/answers/{_escape_pointer(field.field_id)}"}
    accessibility = {"label": field.label, "description": field.help_text}
    if field.kind == "short_text":
        return {
            "id": component_id,
            "component": "TextField",
            "label": field.label,
            "value": binding,
            "variant": "shortText",
            "accessibility": accessibility,
        }
    if field.kind in {"single_select", "multi_select"}:
        return {
            "id": component_id,
            "component": "ChoicePicker",
            "label": field.label,
            "variant": (
                "mutuallyExclusive" if field.kind == "single_select" else "multipleSelection"
            ),
            "options": [{"label": choice, "value": choice} for choice in field.choices],
            "value": binding,
            "displayStyle": "checkbox",
            "filterable": False,
            "accessibility": accessibility,
        }
    return {
        "id": component_id,
        "component": "CheckBox",
        "label": field.label,
        "value": binding,
        "accessibility": accessibility,
    }


def _initial_answer(field: ScopeField) -> str | bool | list[str]:
    if field.kind == "boolean":
        return False
    if field.kind in {"single_select", "multi_select"}:
        return []
    return ""


def _action_context(
    session_id: str,
    proposal: ScopeProposal,
    *,
    include_answers: bool,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "sessionId": session_id,
        "proposalId": proposal.proposal_id,
        "proposalVersion": proposal.schema_version,
    }
    if include_answers:
        context["answers"] = {"path": "/answers"}
    return context


def _validate_messages(messages: list[dict[str, Any]], surface_id: str) -> None:
    if len(messages) != 3:
        raise ValueError("A2UI intake surfaces require exactly three messages.")
    encoded = json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 128 * 1024:
        raise ValueError("A2UI message list exceeds the allowed size.")
    if _json_depth(messages) > 12:
        raise ValueError("A2UI message nesting exceeds the allowed depth.")
    _A2UI_VALIDATOR.validate(_CATALOG_VALIDATOR, messages)

    expected_operations = ("createSurface", "updateDataModel", "updateComponents")
    for message, operation in zip(messages, expected_operations, strict=True):
        if set(message) != {"version", operation} or message["version"] != A2UI_WIRE_VERSION:
            raise ValueError("A2UI messages have an unsupported operation or ordering.")
        if message[operation].get("surfaceId") != surface_id:
            raise ValueError("A2UI messages must target one surface.")

    if messages[0]["createSurface"] != {
        "surfaceId": surface_id,
        "catalogId": A2UI_CATALOG_ID,
        "sendDataModel": False,
    }:
        raise ValueError("A2UI surface creation has unsupported properties.")
    if set(messages[1]["updateDataModel"]) != {"surfaceId", "value"}:
        raise ValueError("A2UI data update has unsupported properties.")
    if set(messages[2]["updateComponents"]) != {"surfaceId", "components"}:
        raise ValueError("A2UI component update has unsupported properties.")

    components = messages[2]["updateComponents"]["components"]
    if len(components) > MAX_A2UI_COMPONENTS:
        raise ValueError("A2UI surface contains too many components.")
    if any(component.get("component") not in ALLOWED_COMPONENTS for component in components):
        raise ValueError("A2UI surface contains a component outside the intake catalog.")
    for component in components:
        _validate_component_properties(component)
        action = component.get("action")
        if action is None:
            continue
        event = action.get("event") if isinstance(action, dict) else None
        if not isinstance(event, dict) or event.get("name") not in ALLOWED_ACTIONS:
            raise ValueError("A2UI surface contains an unsupported action.")

    by_id = {component["id"]: component for component in components}
    if _component_depth("root", by_id, seen=frozenset()) > MAX_A2UI_COMPONENT_DEPTH:
        raise ValueError("A2UI component nesting exceeds the allowed depth.")


def _validate_bindings_and_actions(
    components: list[dict[str, Any]],
    *,
    answers: set[str],
    identity: dict[str, str],
) -> None:
    expected_paths = {f"/answers/{_escape_pointer(answer)}" for answer in answers}
    bound_paths: set[str] = set()
    action_names: set[str] = set()
    for component in components:
        if component.get("component") in {"TextField", "ChoicePicker", "CheckBox"}:
            value = component.get("value")
            if not isinstance(value, dict) or set(value) != {"path"}:
                raise ValueError("A2UI input values require one direct data binding.")
            path = value.get("path")
            if path not in expected_paths:
                raise ValueError("A2UI input binding targets an unknown answer.")
            bound_paths.add(path)
        action = component.get("action")
        if action is None:
            continue
        event = action["event"]
        name = event["name"]
        context = event.get("context")
        expected_context: dict[str, Any] = dict(identity)
        if name == SUBMIT_EVENT_NAME:
            expected_context["answers"] = {"path": "/answers"}
        if context != expected_context:
            raise ValueError("A2UI action context is not strictly bound to this proposal.")
        action_names.add(name)
    if bound_paths != expected_paths:
        raise ValueError("Every A2UI answer must have exactly one reachable input binding.")
    if action_names != ALLOWED_ACTIONS:
        raise ValueError("A2UI surface requires exact submit and skip actions.")


def _validate_component_properties(component: dict[str, Any]) -> None:
    component_type = component["component"]
    if set(component) != _COMPONENT_PROPERTIES[component_type]:
        raise ValueError("A2UI component contains unsupported properties.")
    for key in ("text", "label"):
        if key in component and not isinstance(component[key], str):
            raise ValueError("A2UI display values must be literal text.")
    accessibility = component.get("accessibility")
    if accessibility is not None and (
        not isinstance(accessibility, dict)
        or set(accessibility) - {"label", "description"}
        or any(not isinstance(value, str) for value in accessibility.values())
    ):
        raise ValueError("A2UI accessibility values must be literal text.")
    options = component.get("options")
    if options is not None and any(
        not isinstance(option, dict)
        or set(option) != {"label", "value"}
        or not isinstance(option["label"], str)
        or not isinstance(option["value"], str)
        for option in options
    ):
        raise ValueError("A2UI choice options must be bounded literal values.")


def _valid_answer_value(value: Any) -> bool:
    if isinstance(value, bool | str):
        return True
    return (
        isinstance(value, list) and len(value) <= 8 and all(isinstance(item, str) for item in value)
    )


def _component_depth(
    component_id: str,
    components: dict[str, dict[str, Any]],
    *,
    seen: frozenset[str],
) -> int:
    if component_id in seen:
        raise ValueError("A2UI component graph contains a cycle.")
    component = components[component_id]
    references: list[str] = []
    if isinstance(component.get("children"), list):
        references.extend(component["children"])
    if isinstance(component.get("child"), str):
        references.append(component["child"])
    if not references:
        return 1
    next_seen = seen | {component_id}
    return 1 + max(
        _component_depth(reference, components, seen=next_seen) for reference in references
    )


def _json_depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max((_json_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(item) for item in value), default=0)
    return 0


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


__all__ = [
    "A2UI_SURFACE_EVENT_NAME",
    "A2uiCompilationError",
    "DurableA2uiProjector",
    "compile_intake_surface",
    "validate_intake_surface",
]
