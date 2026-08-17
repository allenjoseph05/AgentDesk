"""Shared deterministic fixture library coverage."""

import json
from pathlib import Path

import pytest

from packages.testing import list_research_fixtures, load_research_fixture


def test_manifest_is_frontend_readable_and_covers_required_scenarios() -> None:
    entries = list_research_fixtures()
    raw = json.loads(Path("fixtures/research/manifest.json").read_text(encoding="utf-8"))

    assert {entry.kind for entry in entries} == {"good", "partial", "contradictory", "failure"}
    assert [entry.fixture_id for entry in entries if entry.golden] == [
        "postgresql-vs-mongodb-golden"
    ]
    assert len(raw["fixtures"]) == 4


def test_every_shared_fixture_loads_as_strict_domain_models() -> None:
    fixtures = [load_research_fixture(entry.fixture_id) for entry in list_research_fixtures()]

    assert all("PostgreSQL" in fixture.request.options for fixture in fixtures)
    assert all("MongoDB" in fixture.request.options for fixture in fixtures)
    golden = fixtures[0]
    assert golden.evidence_bundle is not None
    assert golden.decision_analysis is not None
    assert golden.verification_report is not None


def test_partial_contradictory_and_failure_semantics_are_preserved() -> None:
    partial = load_research_fixture("postgresql-vs-mongodb-partial")
    contradictory = load_research_fixture("postgresql-vs-mongodb-contradictory")
    failure = load_research_fixture("postgresql-vs-mongodb-failure")

    assert partial.evidence_bundle is not None and len(partial.evidence_bundle.unknowns) >= 2
    assert contradictory.evidence_bundle is not None
    assert len(contradictory.evidence_bundle.claims) == 2
    assert failure.failure is not None and failure.failure.retryable is True
    assert failure.evidence_bundle is None


def test_unknown_fixture_id_is_rejected() -> None:
    with pytest.raises(KeyError, match="Unknown research fixture"):
        load_research_fixture("not-in-the-manifest")
