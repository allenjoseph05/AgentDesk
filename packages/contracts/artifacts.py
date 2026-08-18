"""Versioned envelopes for cross-agent artifacts."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel

from packages.contracts.base import ContractModel, NonEmptyText

DOMAIN_SCHEMA_VERSION: Literal["1.0"] = "1.0"


class ArtifactProvenance(ContractModel):
    """Transport metadata identifying who produced an artifact and when."""

    producer_agent: NonEmptyText
    remote_task_id: NonEmptyText
    created_at: AwareDatetime


class ArtifactEnvelope[PayloadT: BaseModel](ContractModel):
    """Carry a typed payload with its required domain schema version."""

    schema_version: Literal["1.0"] = DOMAIN_SCHEMA_VERSION
    provenance: ArtifactProvenance
    payload: PayloadT
