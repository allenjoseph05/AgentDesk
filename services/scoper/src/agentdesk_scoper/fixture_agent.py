"""Deterministic ADK agent used only by compatibility probes and tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types as genai_types

SCOPE_FIXTURE = {
    "schema_version": "1.0",
    "proposal_id": "compatibility-proposal",
    "question": "Should the product use PostgreSQL or MongoDB?",
    "summary": "Clarify the decision criteria before research starts.",
}


class FixtureScoperAgent(BaseAgent):
    """Run the ADK lifecycle deterministically without a model or credential."""

    delay_seconds: float = 0.0
    malformed_output: bool = False

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event]:
        yield self._text_event(ctx, "Scoping the decision request.", partial=True)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        output = "{malformed-json" if self.malformed_output else json.dumps(SCOPE_FIXTURE)
        yield self._text_event(ctx, output, partial=False)

    def _text_event(self, ctx: InvocationContext, text: str, *, partial: bool) -> Event:
        return Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            partial=partial,
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part(text=text)],
            ),
        )
