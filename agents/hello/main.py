"""FastAPI entry point for the standalone A2A hello agent."""

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

from agents.hello.agent_card import create_agent_card
from agents.hello.executor import HelloAgentExecutor

DEFAULT_BASE_URL = "http://127.0.0.1:8004"


def create_app(
    base_url: str | None = None,
    executor: HelloAgentExecutor | None = None,
) -> FastAPI:
    """Create an independently runnable A2A hello-agent application."""
    public_url = (base_url or os.getenv("HELLO_AGENT_URL") or DEFAULT_BASE_URL).rstrip("/")
    agent_card = create_agent_card(public_url)
    request_handler = DefaultRequestHandler(
        agent_executor=executor or HelloAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await request_handler.aclose()

    application = FastAPI(
        title="AgentDesk Hello Agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"service": "hello-agent", "status": "ok"}

    add_a2a_routes_to_fastapi(
        application,
        agent_card_routes=create_agent_card_routes(agent_card),
        rest_routes=create_rest_routes(request_handler),
    )
    return application


app = create_app()
