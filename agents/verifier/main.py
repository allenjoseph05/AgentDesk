"""FastAPI entry point for the independently runnable Verifier Agent."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_rest_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI

from agents.verifier.agent_card import create_agent_card
from agents.verifier.executor import VerifierAgentExecutor
from packages.config import load_project_environment
from packages.observability import configure_structured_logging, configure_tracing

load_project_environment()
configure_structured_logging()
TRACING = configure_tracing("agentdesk-verifier")

DEFAULT_BASE_URL = "http://127.0.0.1:8007"


def create_app(
    base_url: str | None = None,
    executor: VerifierAgentExecutor | None = None,
) -> FastAPI:
    """Create a Verifier Agent instance with operations and A2A routes."""
    public_url = (base_url or os.getenv("VERIFIER_AGENT_URL") or DEFAULT_BASE_URL).rstrip("/")
    agent_card = create_agent_card(public_url)
    request_handler = DefaultRequestHandler(
        agent_executor=executor or VerifierAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await request_handler.aclose()
            TRACING.shutdown()

    application = FastAPI(
        title="AgentDesk Verifier Agent",
        description="Independent A2A specialist for evidence-bound fact verification.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"service": "verifier-agent", "status": "ok"}

    @application.get("/ready", tags=["operations"])
    async def ready() -> dict[str, str]:
        return {"service": "verifier-agent", "status": "ready"}

    add_a2a_routes_to_fastapi(
        application,
        agent_card_routes=create_agent_card_routes(agent_card),
        rest_routes=create_rest_routes(request_handler),
    )
    return application


app = create_app()
