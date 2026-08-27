"""Deterministic probe for Google ADK's experimental native A2A bridge.

This module is compatibility evidence only. It is intentionally absent from the
AgentDesk runtime and Compose topology.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from starlette.applications import Starlette

from agentdesk_scoper.fixture_agent import FixtureScoperAgent
from agentdesk_scoper.native_contract import create_native_agent_card

DEFAULT_BASE_URL = "http://127.0.0.1:8010"


def create_native_bridge_app(
    base_url: str = DEFAULT_BASE_URL,
    *,
    delay_seconds: float = 0.0,
    malformed_output: bool = False,
) -> Starlette:
    """Create the isolated native-bridge probe application."""
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("The compatibility URL must be an absolute HTTP(S) URL.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("The compatibility URL must not contain a path, query, or fragment.")
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    agent = FixtureScoperAgent(
        name="decision_scoper",
        description="Deterministic ADK decision-scoping compatibility agent.",
        delay_seconds=delay_seconds,
        malformed_output=malformed_output,
    )
    return to_a2a(
        agent,
        host=parsed.hostname,
        port=port,
        protocol=parsed.scheme,
        agent_card=create_native_agent_card(base_url),
    )


app = create_native_bridge_app(
    os.getenv("SCOPER_COMPAT_URL", DEFAULT_BASE_URL),
    delay_seconds=float(os.getenv("SCOPER_FIXTURE_DELAY_SECONDS", "0")),
    malformed_output=os.getenv("SCOPER_FIXTURE_MALFORMED", "0") == "1",
)
