"""Bounded adaptive-intake contracts shared by the Coordinator and scoper."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    StrictBool,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from packages.contracts.agui import MAX_AG_UI_TEXT_LENGTH
from packages.contracts.artifacts import ArtifactEnvelope
from packages.contracts.base import ContractModel
from packages.contracts.domain import Depth

INTAKE_SCHEMA_VERSION: Literal["1.0"] = "1.0"
SCOPE_PROPOSAL_ARTIFACT_NAME = "scope-proposal"
MAX_INTAKE_TEXT_LENGTH = MAX_AG_UI_TEXT_LENGTH
MAX_SCOPE_SUMMARY_LENGTH = 1024
MAX_SCOPE_FIELDS = 8
MAX_SCOPE_CHOICES = 8
MAX_INTAKE_ARTIFACT_BYTES = 256 * 1024
MAX_INTAKE_RESPONSE_BYTES = 64 * 1024
MAX_SUGGESTED_OPTIONS = 4
MAX_SUGGESTED_CRITERIA = 8
MAX_SUGGESTED_CONSTRAINTS = 8

FieldDestination = Literal["option", "criterion", "constraint"]
FieldKind = Literal["short_text", "single_select", "multi_select", "boolean"]
IntakeIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_-]*$",
    ),
]
IntakeReference = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
IntakeText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_INTAKE_TEXT_LENGTH),
]
ShortSummary = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SCOPE_SUMMARY_LENGTH),
]
StrictAnswerText = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_INTAKE_TEXT_LENGTH),
]
type IntakeAnswer = StrictAnswerText | list[StrictAnswerText] | StrictBool

_MARKUP = re.compile(r"<\s*/?\s*[a-z][^>]*>", re.IGNORECASE)
_ACTIVE_CONTENT = re.compile(r"(?:https?|javascript|data):|\{\{|\$\{", re.IGNORECASE)


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(value.split())).lower()


def _validate_plain_text(value: str) -> str:
    if _MARKUP.search(value) or _ACTIVE_CONTENT.search(value):
        raise ValueError("Intake display text must not contain markup, URLs, or expressions.")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise ValueError("Intake display text must not contain control characters.")
    return value


def _require_unique(values: list[str], label: str) -> None:
    normalized = [_normalized(value) for value in values]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must be unique after normalization.")


class ScopeField(ContractModel):
    """One trusted field description emitted by the decision-scoping agent."""

    field_id: IntakeIdentifier
    label: IntakeText
    help_text: IntakeText
    required: bool
    destination: FieldDestination
    kind: FieldKind
    choices: list[IntakeText] = Field(default_factory=list, max_length=MAX_SCOPE_CHOICES)

    @field_validator("label", "help_text")
    @classmethod
    def validate_display_text(cls, value: str) -> str:
        return _validate_plain_text(value)

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, values: list[str]) -> list[str]:
        for value in values:
            _validate_plain_text(value)
        _require_unique(values, "Field choices")
        return values

    @model_validator(mode="after")
    def validate_kind_and_choices(self) -> ScopeField:
        if self.kind in {"single_select", "multi_select"} and not self.choices:
            raise ValueError("Select fields require at least one choice.")
        if self.kind in {"short_text", "boolean"} and self.choices:
            raise ValueError("Short-text and boolean fields cannot define choices.")
        if self.kind == "boolean" and self.destination == "option":
            raise ValueError("Boolean fields cannot populate research options.")
        return self


class ScopeProposal(ContractModel):
    """Validated decision-scoping result before it is compiled into A2UI."""

    schema_version: Literal["1.0"] = INTAKE_SCHEMA_VERSION
    proposal_id: IntakeReference
    question: IntakeText
    summary: ShortSummary
    fields: list[ScopeField] = Field(min_length=1, max_length=MAX_SCOPE_FIELDS)
    suggested_options: list[IntakeText] = Field(
        default_factory=list,
        max_length=MAX_SUGGESTED_OPTIONS,
    )
    suggested_criteria: list[IntakeText] = Field(
        min_length=1,
        max_length=MAX_SUGGESTED_CRITERIA,
    )
    suggested_constraints: list[IntakeText] = Field(
        default_factory=list,
        max_length=MAX_SUGGESTED_CONSTRAINTS,
    )
    default_depth: Depth = "normal"

    @field_validator("summary", "suggested_options", "suggested_criteria", "suggested_constraints")
    @classmethod
    def validate_plain_values(cls, value: str | list[str]) -> str | list[str]:
        values = [value] if isinstance(value, str) else value
        for item in values:
            _validate_plain_text(item)
        if isinstance(value, list):
            _require_unique(value, "Suggested values")
        return value

    @model_validator(mode="after")
    def validate_structure_and_feasibility(self) -> ScopeProposal:
        field_ids = [_normalized(field.field_id) for field in self.fields]
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("Scope field IDs must be unique after normalization.")

        option_capacity = len(self.suggested_options)
        option_fields = [field for field in self.fields if field.destination == "option"]
        for field in option_fields:
            option_capacity += len(field.choices) if field.kind == "multi_select" else 1
        if option_capacity < 2:
            raise ValueError("A scope proposal must make at least two options possible.")
        if len(self.suggested_options) < 2 and not any(field.required for field in option_fields):
            raise ValueError("Incomplete suggested options require a required option field.")
        return self


class ScopeProposalArtifact(ArtifactEnvelope[ScopeProposal]):
    """Versioned A2A artifact envelope for the decision-scoping skill."""

    @model_validator(mode="after")
    def validate_encoded_size(self) -> ScopeProposalArtifact:
        _require_json_size(self.model_dump(mode="json"), MAX_INTAKE_ARTIFACT_BYTES, "artifact")
        return self


class IntakeResponse(ContractModel):
    """Bounded browser answers tied to one immutable proposal version."""

    schema_version: Literal["1.0"] = INTAKE_SCHEMA_VERSION
    session_id: IntakeReference
    proposal_id: IntakeReference
    proposal_version: Literal["1.0"] = INTAKE_SCHEMA_VERSION
    answers: dict[IntakeIdentifier, IntakeAnswer] = Field(max_length=MAX_SCOPE_FIELDS)

    @field_validator("answers")
    @classmethod
    def validate_answer_lists(
        cls,
        answers: dict[str, IntakeAnswer],
    ) -> dict[str, IntakeAnswer]:
        for value in answers.values():
            if isinstance(value, list):
                if len(value) > MAX_SCOPE_CHOICES:
                    raise ValueError("An intake answer contains too many selected values.")
                _require_unique(value, "Selected values")
        return answers

    @model_validator(mode="after")
    def validate_encoded_size(self) -> IntakeResponse:
        _require_json_size(self.model_dump(mode="json"), MAX_INTAKE_RESPONSE_BYTES, "response")
        return self


def parse_scope_proposal_artifact(value: Any) -> ScopeProposalArtifact:
    """Apply the serialized-size gate before validating an untrusted artifact value."""

    _require_json_size(value, MAX_INTAKE_ARTIFACT_BYTES, "artifact")
    return ScopeProposalArtifact.model_validate(value)


def parse_intake_response(value: Any) -> IntakeResponse:
    """Apply the serialized-size gate before validating an untrusted response value."""

    _require_json_size(value, MAX_INTAKE_RESPONSE_BYTES, "response")
    return IntakeResponse.model_validate(value)


def validate_intake_response(
    proposal: ScopeProposal,
    response: IntakeResponse | dict[str, Any],
) -> IntakeResponse:
    """Validate an intake response against the exact proposal that created its surface."""

    validated = (
        response if isinstance(response, IntakeResponse) else parse_intake_response(response)
    )
    if validated.proposal_id != proposal.proposal_id:
        raise ValueError("Intake response proposal ID does not match the proposal.")
    if validated.proposal_version != proposal.schema_version:
        raise ValueError("Intake response proposal version is stale or unsupported.")

    fields = {field.field_id: field for field in proposal.fields}
    unknown = set(validated.answers) - set(fields)
    if unknown:
        raise ValueError(f"Intake response contains unknown fields: {sorted(unknown)}")
    missing = {field.field_id for field in proposal.fields if field.required} - set(
        validated.answers
    )
    if missing:
        raise ValueError(f"Intake response is missing required fields: {sorted(missing)}")

    for field_id, answer in validated.answers.items():
        field = fields[field_id]
        if field.kind in {"short_text", "single_select"} and not isinstance(answer, str):
            raise ValueError(f"Field {field_id} requires one text value.")
        if field.kind == "multi_select" and not isinstance(answer, list):
            raise ValueError(f"Field {field_id} requires a list of text values.")
        if field.kind == "boolean" and not isinstance(answer, bool):
            raise ValueError(f"Field {field_id} requires a boolean value.")
        if field.required and isinstance(answer, list) and not answer:
            raise ValueError(f"Required field {field_id} cannot be empty.")
        if field.choices:
            selected = (
                answer if isinstance(answer, list) else [answer] if isinstance(answer, str) else []
            )
            allowed = {_normalized(choice) for choice in field.choices}
            invalid = [
                value
                for value in selected
                if isinstance(value, str) and _normalized(value) not in allowed
            ]
            if invalid:
                raise ValueError(f"Field {field_id} contains values outside its declared choices.")
    return validated


def _require_json_size(value: Any, maximum: int, label: str) -> None:
    try:
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"Intake {label} must be JSON-safe.") from error
    if len(encoded) > maximum:
        raise ValueError(f"Intake {label} exceeds the allowed size.")
