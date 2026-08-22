"""Runnable Coordinator service shell."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

from agents.coordinator.agui import router as ag_ui_router
from agents.coordinator.agui_security import (
    CORRELATION_HEADER,
    AgUiBoundaryError,
    AgUiSecurityMiddleware,
)
from agents.coordinator.execution import create_orchestration_executor
from agents.coordinator.history import ResearchHistoryService
from agents.coordinator.history_api import router as history_router
from agents.coordinator.registry import AgentRegistry, AgentRegistrySettings
from agents.coordinator.run_adapter import (
    A2ATaskCommandExecutor,
    CoordinatorCommandExecutor,
    CoordinatorRunAdapter,
)
from agents.coordinator.run_tasks import A2ATaskFactory
from packages.config import load_project_environment
from packages.observability import (
    CorrelationIds,
    configure_structured_logging,
    configure_tracing,
    log_event,
)
from packages.persistence import Database

load_project_environment()
configure_structured_logging()
TRACING = configure_tracing("agentdesk-coordinator")
LOGGER = logging.getLogger(__name__)


def create_app(
    task_factory: A2ATaskFactory | None = None,
    *,
    registry: AgentRegistry | None = None,
    registry_settings: AgentRegistrySettings | None = None,
    command_executor: CoordinatorCommandExecutor | None = None,
    database: Database | None = None,
) -> FastAPI:
    """Create a Coordinator with application-scoped AG-UI run admission."""
    if task_factory is not None and command_executor is not None:
        raise ValueError("Supply either task_factory or command_executor, not both.")
    owns_registry = registry is None
    owns_database = database is None
    history_database = database or Database.connect()
    agent_registry = registry or AgentRegistry(
        registry_settings or AgentRegistrySettings.from_environment()
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await agent_registry.refresh()
        try:
            yield
        finally:
            if owns_registry:
                await agent_registry.aclose()
            if owns_database:
                history_database.dispose()
            TRACING.shutdown()

    application = FastAPI(
        title="AgentDesk Coordinator",
        description="Coordinator shell exposing the browser-facing AG-UI boundary.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(AgUiSecurityMiddleware)

    @application.exception_handler(AgUiBoundaryError)
    async def ag_ui_boundary_error(
        request: Request,
        error: AgUiBoundaryError,
    ) -> JSONResponse:
        return _protocol_error_response(request, error)

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> Response:
        if request.url.path != "/ag-ui":
            return await request_validation_exception_handler(request, error)
        return _protocol_error_response(
            request,
            AgUiBoundaryError(
                "invalid_agui_input",
                "The AG-UI request does not match the supported protocol shape.",
                status_code=422,
            ),
        )
    executor = command_executor or (
        A2ATaskCommandExecutor(task_factory)
        if task_factory is not None
        else create_orchestration_executor(
            registry=agent_registry,
            database=history_database,
        )
    )
    application.state.ag_ui_run_adapter = CoordinatorRunAdapter(executor=executor)
    application.state.agent_registry = agent_registry
    application.state.research_history = ResearchHistoryService(history_database)
    application.include_router(ag_ui_router)
    application.include_router(history_router)

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


def _protocol_error_response(
    request: Request,
    error: AgUiBoundaryError,
) -> JSONResponse:
    correlation_id = getattr(
        request.state,
        "agentdesk_correlation_id",
        "unavailable",
    )
    log_event(
        LOGGER,
        "agui.protocol_rejected",
        level=logging.WARNING,
        ids=CorrelationIds(correlation_id=correlation_id, agent="coordinator"),
        outcome="failed",
        error_code=error.code,
    )
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": str(error),
                "correlationId": correlation_id,
            }
        },
        headers={CORRELATION_HEADER: correlation_id},
    )


app = create_app()
