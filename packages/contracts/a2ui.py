"""Bounded A2UI surface contract transported inside AG-UI custom events."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, StringConstraints, model_validator

from packages.contracts.base import ContractModel

A2UI_EVENT_SCHEMA_VERSION: Literal["1.0"] = "1.0"
A2UI_PROTOCOL_VERSION: Literal["0.9.1"] = "0.9.1"
A2UI_WIRE_VERSION: Literal["v0.9"] = "v0.9"
A2UI_CATALOG_ID: Literal["agentdesk.dev:intake-v1"] = "agentdesk.dev:intake-v1"
A2UI_CATALOG_VERSION: Literal["1.0"] = "1.0"
A2UI_SURFACE_EVENT_NAME = "agentdesk.a2ui.surface.v1"
MAX_A2UI_MESSAGES = 3
MAX_A2UI_SURFACE_BYTES = 128 * 1024

A2uiIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class A2uiSurface(ContractModel):
    """One validated, complete intake surface carried as an AG-UI event value."""

    schema_version: Literal["1.0"] = Field(
        default=A2UI_EVENT_SCHEMA_VERSION,
        validation_alias=AliasChoices("schemaVersion", "schema_version"),
        serialization_alias="schemaVersion",
    )
    session_id: A2uiIdentifier = Field(
        validation_alias=AliasChoices("sessionId", "session_id"),
        serialization_alias="sessionId",
    )
    proposal_id: A2uiIdentifier = Field(
        validation_alias=AliasChoices("proposalId", "proposal_id"),
        serialization_alias="proposalId",
    )
    proposal_version: Literal["1.0"] = Field(
        validation_alias=AliasChoices("proposalVersion", "proposal_version"),
        serialization_alias="proposalVersion",
    )
    surface_id: A2uiIdentifier = Field(
        validation_alias=AliasChoices("surfaceId", "surface_id"),
        serialization_alias="surfaceId",
    )
    catalog_id: Literal["agentdesk.dev:intake-v1"] = Field(
        default=A2UI_CATALOG_ID,
        validation_alias=AliasChoices("catalogId", "catalog_id"),
        serialization_alias="catalogId",
    )
    catalog_version: Literal["1.0"] = Field(
        default=A2UI_CATALOG_VERSION,
        validation_alias=AliasChoices("catalogVersion", "catalog_version"),
        serialization_alias="catalogVersion",
    )
    protocol_version: Literal["0.9.1"] = Field(
        default=A2UI_PROTOCOL_VERSION,
        validation_alias=AliasChoices("protocolVersion", "protocol_version"),
        serialization_alias="protocolVersion",
    )
    wire_version: Literal["v0.9"] = Field(
        default=A2UI_WIRE_VERSION,
        validation_alias=AliasChoices("wireVersion", "wire_version"),
        serialization_alias="wireVersion",
    )
    messages: list[dict[str, Any]] = Field(min_length=3, max_length=MAX_A2UI_MESSAGES)

    @model_validator(mode="after")
    def validate_bounded_json(self) -> A2uiSurface:
        encoded = json.dumps(
            self.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > MAX_A2UI_SURFACE_BYTES:
            raise ValueError("A2UI surface exceeds the allowed size.")
        return self

    def to_ag_ui(self) -> dict[str, Any]:
        """Serialize using the browser-facing camelCase contract."""
        return self.model_dump(mode="json", by_alias=True)
