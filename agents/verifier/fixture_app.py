"""Runnable deterministic Verifier Agent configuration for contract tests."""

from __future__ import annotations

import asyncio
import os

from pydantic import BaseModel

from agents.verifier.executor import VerifierAgentExecutor
from agents.verifier.main import create_app
from agents.verifier.verification import ClaimVerifier
from packages.contracts import VerificationReport
from packages.llm import FakeLLMProvider, Message
from packages.testing import load_research_fixture

DEFAULT_FIXTURE_ID = "postgresql-vs-mongodb-golden"


class DelayedFixtureLLMProvider:
    """Apply a fixed recording delay before returning verifier fixture data."""

    def __init__(self, provider: FakeLLMProvider, delay_seconds: float) -> None:
        if delay_seconds < 0:
            raise ValueError("Fixture verification delay cannot be negative.")
        self._provider = provider
        self._delay_seconds = delay_seconds

    async def generate_structured[ResponseT: BaseModel](
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        response_model: type[ResponseT],
    ) -> ResponseT:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        return await self._provider.generate_structured(
            system_prompt=system_prompt,
            messages=messages,
            response_model=response_model,
        )


def create_fixture_executor(
    fixture_id: str = DEFAULT_FIXTURE_ID,
    *,
    verification_delay_seconds: float = 0,
) -> VerifierAgentExecutor:
    """Compose the production Verifier boundary with deterministic output."""
    fixture = load_research_fixture(fixture_id)
    if fixture.evidence_bundle is None or fixture.verification_report is None:
        raise ValueError(f"Verifier fixture requires evidence and verification: {fixture_id}")
    return VerifierAgentExecutor(
        ClaimVerifier(
            DelayedFixtureLLMProvider(
                FakeLLMProvider({VerificationReport: fixture.verification_report}),
                verification_delay_seconds,
            )
        )
    )


_fixture_id = os.getenv("VERIFIER_FIXTURE_ID", DEFAULT_FIXTURE_ID)
_verification_delay = float(os.getenv("VERIFIER_FIXTURE_DELAY_SECONDS", "0"))
app = create_app(
    executor=create_fixture_executor(
        _fixture_id,
        verification_delay_seconds=_verification_delay,
    )
)
