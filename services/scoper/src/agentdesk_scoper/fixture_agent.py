"""Deterministic ADK agent for free local execution and compatibility tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types as genai_types

SCOPE_FIXTURE: dict[str, Any] = {
    "schema_version": "1.0",
    "proposal_id": "compatibility-proposal",
    "question": "Should the product use PostgreSQL or MongoDB?",
    "summary": "Clarify the decision criteria before research starts.",
    "fields": [
        {
            "field_id": "operating_priority",
            "label": "Primary operating priority",
            "help_text": "Choose the quality that should drive the comparison.",
            "required": True,
            "destination": "criterion",
            "kind": "single_select",
            "choices": ["Data integrity", "Developer velocity", "Operational simplicity"],
        }
    ],
    "suggested_options": ["PostgreSQL", "MongoDB"],
    "suggested_criteria": ["Data model fit"],
    "suggested_constraints": [],
    "default_depth": "normal",
}


class FixtureScoperAgent(BaseAgent):
    """Run the ADK lifecycle deterministically without a model or credential."""

    delay_seconds: float = 0.0
    malformed_output: bool = False
    proposal_template: dict[str, Any] | None = None
    bind_request_identifiers: bool = True

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event]:
        yield self._text_event(ctx, "Scoping the decision request.", partial=True)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        output = "{malformed-json" if self.malformed_output else json.dumps(self._proposal(ctx))
        yield self._text_event(ctx, output, partial=False)

    def _proposal(self, ctx: InvocationContext) -> dict[str, Any]:
        proposal = dict(self.proposal_template or SCOPE_FIXTURE)
        content = ctx.user_content
        text = next(
            (part.text for part in (content.parts if content else []) if part.text),
            None,
        )
        if text and self.bind_request_identifiers:
            try:
                command = json.loads(text)
            except json.JSONDecodeError:
                command = None
            if isinstance(command, dict):
                if isinstance(command.get("proposal_id"), str):
                    proposal["proposal_id"] = command["proposal_id"]
                if isinstance(command.get("question"), str):
                    proposal["question"] = command["question"]
        return proposal

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
