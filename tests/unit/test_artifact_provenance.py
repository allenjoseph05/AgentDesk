"""Artifact envelope provenance boundary tests."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from packages.contracts import (
    ArtifactEnvelope,
    ArtifactProvenance,
    EvidenceBundle,
)


def _payload() -> EvidenceBundle:
    return EvidenceBundle(
        question="Which database should be selected?",
        claims=[],
        evidence=[],
        unknowns=["Workload measurements are pending."],
    )


def _provenance() -> ArtifactProvenance:
    return ArtifactProvenance(
        producer_agent="researcher",
        remote_task_id="remote-task-42",
        created_at=datetime(2026, 8, 16, 14, 30, tzinfo=UTC),
    )


def test_every_envelope_requires_complete_provenance() -> None:
    envelope = ArtifactEnvelope[EvidenceBundle](
        provenance=_provenance(),
        payload=_payload(),
    )

    assert envelope.schema_version == "1.0"
    assert envelope.provenance.producer_agent == "researcher"
    assert envelope.provenance.remote_task_id == "remote-task-42"
    assert envelope.provenance.created_at.tzinfo is not None


def test_provenance_is_not_mixed_into_domain_payload() -> None:
    dumped = ArtifactEnvelope[EvidenceBundle](
        provenance=_provenance(),
        payload=_payload(),
    ).model_dump(mode="json")

    assert set(dumped) == {"schema_version", "provenance", "payload"}
    assert set(dumped["provenance"]) == {"producer_agent", "remote_task_id", "created_at"}
    assert not ({"producer_agent", "remote_task_id", "created_at"} & set(dumped["payload"]))


@pytest.mark.parametrize(
    "provenance",
    [
        {},
        {
            "producer_agent": " ",
            "remote_task_id": "remote-task-42",
            "created_at": datetime.now(UTC),
        },
        {
            "producer_agent": "researcher",
            "remote_task_id": " ",
            "created_at": datetime.now(UTC),
        },
        {
            "producer_agent": "researcher",
            "remote_task_id": "remote-task-42",
            "created_at": datetime(2026, 8, 16, 14, 30),
        },
    ],
)
def test_envelope_rejects_missing_or_malformed_provenance(provenance: dict) -> None:
    with pytest.raises(ValidationError):
        ArtifactEnvelope[EvidenceBundle].model_validate(
            {"provenance": provenance, "payload": _payload().model_dump()}
        )


def test_envelope_rejects_missing_provenance_object() -> None:
    with pytest.raises(ValidationError):
        ArtifactEnvelope[EvidenceBundle](payload=_payload())
