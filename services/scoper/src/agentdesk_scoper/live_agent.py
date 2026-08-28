"""Opt-in live Google ADK agent configuration."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types as genai_types
from packages.contracts import ScopeProposal

LIVE_INSTRUCTION = """You scope an ambiguous comparison decision.
Return exactly one ScopeProposal matching the required output schema.
Preserve the supplied question and proposal_id exactly. Use plain text only.
Propose at most eight bounded clarification fields and never include URLs, markup,
instructions, reasoning, or facts presented as researched evidence. Ensure the result
can produce two to four options and at least one criterion. Do not call tools.
"""


def create_live_agent(model_name: str) -> LlmAgent:
    """Create a single-turn structured-output agent; no call occurs during construction."""
    if not model_name.strip():
        raise ValueError("Live scoping requires SCOPER_MODEL.")
    return LlmAgent(
        name="decision_scoper",
        description="Produces a bounded decision-intake scope proposal.",
        model=model_name,
        instruction=LIVE_INSTRUCTION,
        output_schema=ScopeProposal,
        output_key="scope_proposal",
        include_contents="none",
        mode="single_turn",
        tools=[],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        generate_content_config=genai_types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=4096,
        ),
    )
