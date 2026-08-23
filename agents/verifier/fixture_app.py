"""Runnable deterministic Verifier Agent configuration for contract tests."""

from __future__ import annotations

import os

from agents.verifier.executor import VerifierAgentExecutor
from agents.verifier.main import create_app
from agents.verifier.verification import ClaimVerifier
from packages.contracts import VerificationReport
from packages.llm import FakeLLMProvider
from packages.testing import load_research_fixture

DEFAULT_FIXTURE_ID = "postgresql-vs-mongodb-golden"


def create_fixture_executor(
    fixture_id: str = DEFAULT_FIXTURE_ID,
) -> VerifierAgentExecutor:
    """Compose the production Verifier boundary with deterministic output."""
    fixture = load_research_fixture(fixture_id)
    if fixture.evidence_bundle is None or fixture.verification_report is None:
        raise ValueError(f"Verifier fixture requires evidence and verification: {fixture_id}")
    return VerifierAgentExecutor(
        ClaimVerifier(FakeLLMProvider({VerificationReport: fixture.verification_report}))
    )


_fixture_id = os.getenv("VERIFIER_FIXTURE_ID", DEFAULT_FIXTURE_ID)
app = create_app(executor=create_fixture_executor(_fixture_id))
