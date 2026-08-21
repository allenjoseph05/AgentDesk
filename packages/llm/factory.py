"""Environment-backed construction for provider-neutral LLM consumers."""

from __future__ import annotations

import os

from packages.llm.openai_provider import OpenAIResponsesProvider
from packages.llm.provider import LLMProvider


def llm_provider_from_environment() -> LLMProvider | None:
    """Return the configured provider, or ``None`` when configuration is incomplete."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("AGENTDESK_COORDINATOR_MODEL", "").strip()
    if not api_key or not model:
        return None
    return OpenAIResponsesProvider(api_key=api_key, model=model)
