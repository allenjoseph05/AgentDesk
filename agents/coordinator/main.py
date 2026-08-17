"""Runnable Coordinator service shell."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agents.coordinator.agui import router as ag_ui_router
from agents.coordinator.registry import AgentRegistry, AgentRegistrySettings
from agents.coordinator.run_tasks import A2ATaskFactory


def create_app(
    task_factory: A2ATaskFactory | None = None,
    *,
    registry: AgentRegistry | None = None,
    registry_settings: AgentRegistrySettings | None = None,
) -> FastAPI:
    """Create a Coordinator with an optional remote-task spike dependency."""
    owns_registry = registry is None
    agent_registry = registry or AgentRegistry(
        registry_settings or AgentRegistrySettings.from_environment()
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await agent_registry.refresh()
        yield
        if owns_registry:
            await agent_registry.aclose()

    application = FastAPI(
        title="AgentDesk Coordinator",
        description="Coordinator shell exposing the browser-facing AG-UI boundary.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.ag_ui_task_factory = task_factory
    application.state.agent_registry = agent_registry
    application.include_router(ag_ui_router)

    @application.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        """Return a minimal readiness signal for local development."""
        return {"service": "coordinator", "status": "ok"}

    @application.get("/ready", tags=["operations"])
    async def ready() -> dict[str, str | int]:
        diagnostics = agent_registry.diagnostics
        return {
            "service": "coordinator",
            "status": "ready" if agent_registry.agents else "degraded",
            "registered_agents": len(agent_registry.agents),
            "diagnostics": len(diagnostics),
        }

    return application


app = create_app()
