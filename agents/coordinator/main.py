"""Runnable Coordinator service shell for the AD-001 repository baseline."""

from fastapi import FastAPI

from agents.coordinator.agui import router as ag_ui_router

app = FastAPI(
    title="AgentDesk Coordinator",
    description="Coordinator development shell; A2A behavior begins in AD-003.",
    version="0.1.0",
)

app.include_router(ag_ui_router)


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    """Return a minimal readiness signal for local development."""
    return {"service": "coordinator", "status": "ok"}
