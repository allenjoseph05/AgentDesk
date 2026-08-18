"""FastAPI entry point for the independently runnable Analyst Agent."""

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

from agents.analyst.agent_card import create_agent_card
from agents.analyst.executor import AnalystAgentExecutor
from packages.config import load_project_environment

load_project_environment()

DEFAULT_BASE_URL = "http://127.0.0.1:8006"


def create_app(
    base_url: str | None = None,
    executor: AnalystAgentExecutor | None = None,
) -> FastAPI:
    """Create an Analyst Agent instance with operations and A2A routes."""
    public_url = (base_url or os.getenv("ANALYST_AGENT_URL") or DEFAULT_BASE_URL).rstrip("/")
    agent_card = create_agent_card(public_url)
    request_handler = DefaultRequestHandler(
        agent_executor=executor or AnalystAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await request_handler.aclose()

    application = FastAPI(
        title="AgentDesk Analyst Agent",
        description="Independent A2A specialist for evidence-bound decision analysis.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"service": "analyst-agent", "status": "ok"}

    @application.get("/ready", tags=["operations"])
    async def ready() -> dict[str, str]:
        return {"service": "analyst-agent", "status": "ready"}

    add_a2a_routes_to_fastapi(
        application,
        agent_card_routes=create_agent_card_routes(agent_card),
        rest_routes=create_rest_routes(request_handler),
    )
    return application


app = create_app()
