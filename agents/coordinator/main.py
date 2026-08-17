"""Runnable Coordinator service shell."""

from fastapi import FastAPI

from agents.coordinator.agui import router as ag_ui_router
from agents.coordinator.run_tasks import A2ATaskFactory


def create_app(task_factory: A2ATaskFactory | None = None) -> FastAPI:
    """Create a Coordinator with an optional remote-task spike dependency."""
    application = FastAPI(
        title="AgentDesk Coordinator",
        description="Coordinator shell exposing the browser-facing AG-UI boundary.",
        version="0.1.0",
    )
    application.state.ag_ui_task_factory = task_factory
    application.include_router(ag_ui_router)

    @application.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        """Return a minimal readiness signal for local development."""
        return {"service": "coordinator", "status": "ok"}

    return application


app = create_app()
