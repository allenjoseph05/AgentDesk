"""Versioned envelopes for cross-agent artifacts."""

from typing import Literal

from pydantic import BaseModel

from packages.contracts.base import ContractModel

DOMAIN_SCHEMA_VERSION = "1.0"


class ArtifactEnvelope[PayloadT: BaseModel](ContractModel):
    """Carry a typed payload with its required domain schema version."""

    schema_version: Literal["1.0"] = DOMAIN_SCHEMA_VERSION
    payload: PayloadT
