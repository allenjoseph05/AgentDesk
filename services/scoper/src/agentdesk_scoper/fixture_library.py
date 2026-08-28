"""Contract-validated, deterministic scoping fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from packages.contracts import ScopeProposal, ScopeProposalArtifact


def load_fixture_proposal(directory: Path, fixture_id: str) -> ScopeProposal:
    """Load only an allowlisted filename and validate its artifact envelope."""
    if not fixture_id or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in fixture_id
    ):
        raise ValueError("Fixture IDs may contain only lowercase letters, digits, and hyphens.")
    path = directory / f"{fixture_id}.golden.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("fixture_id") != fixture_id:
        raise ValueError("Fixture content does not match the selected fixture ID.")
    return ScopeProposalArtifact.model_validate(document["artifact"]).payload
