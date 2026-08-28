"""FastAPI entry point for the independently runnable ADK scoper."""

from __future__ import annotations

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
from fastapi.responses import JSONResponse
from google.adk.agents import BaseAgent

from agentdesk_scoper.agent_card import create_agent_card
from agentdesk_scoper.executor import ScoperAgentExecutor
from agentdesk_scoper.fixture_agent import FixtureScoperAgent
from agentdesk_scoper.fixture_library import load_fixture_proposal
from agentdesk_scoper.live_agent import create_live_agent
from agentdesk_scoper.settings import ScoperSettings


def create_runtime_agent(settings: ScoperSettings) -> BaseAgent:
    """Construct only the provider selected by the explicit runtime mode."""
    if settings.mode == "live" and settings.ready:
        return create_live_agent(settings.model_name or "")
    template = None
    if settings.mode == "fixture" and settings.ready:
        template = load_fixture_proposal(
            settings.fixture_directory,
            settings.fixture_id,
        ).model_dump(mode="json")
    return FixtureScoperAgent(
        name="decision_scoper",
        description="Deterministic decision-scoping agent.",
        proposal_template=template,
    )


def create_app(
    settings: ScoperSettings | None = None,
    *,
    agent: BaseAgent | None = None,
) -> FastAPI:
    resolved = settings or ScoperSettings.from_environment()
    card = create_agent_card(resolved.base_url)
    handler = DefaultRequestHandler(
        agent_executor=ScoperAgentExecutor(agent or create_runtime_agent(resolved), resolved),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await handler.aclose()

    application = FastAPI(
        title="AgentDesk Decision Scoper",
        description="Isolated Google ADK agent exposed over AgentDesk's A2A boundary.",
        version="0.2.0",
        lifespan=lifespan,
    )

    @application.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"service": "decision-scoper", "status": "ok", "mode": resolved.mode}

    @application.get("/ready", tags=["operations"])
    async def ready() -> JSONResponse:
        payload = {
            "service": "decision-scoper",
            "status": "ready" if resolved.ready else "not_ready",
            "mode": resolved.mode,
            "reason": resolved.readiness_reason,
        }
        return JSONResponse(payload, status_code=200 if resolved.ready else 503)

    add_a2a_routes_to_fastapi(
        application,
        agent_card_routes=create_agent_card_routes(card),
        rest_routes=create_rest_routes(handler),
    )
    return application


app = create_app()
