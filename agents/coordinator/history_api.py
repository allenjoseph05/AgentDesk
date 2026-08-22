"""HTTP read boundary for persisted AgentDesk session history."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, Request, status

from agents.coordinator.agui_security import request_principal_id
from agents.coordinator.history import (
    ResearchHistoryService,
    SessionHistoryDetail,
    SessionHistoryNotFoundError,
    SessionHistoryNotReadyError,
    SessionHistoryPage,
)

router = APIRouter(prefix="/api/sessions", tags=["history"])


def _service(request: Request) -> ResearchHistoryService:
    return cast(ResearchHistoryService, request.app.state.research_history)


@router.get("", response_model=SessionHistoryPage)
async def list_sessions(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    thread_id: Annotated[str | None, Query(alias="threadId", min_length=1)] = None,
) -> SessionHistoryPage:
    """List recent persisted sessions for the web history sidebar."""
    return _service(request).list_sessions(
        limit=limit,
        thread_id=thread_id,
        owner_id=request_principal_id(request),
    )


@router.get("/{session_id}", response_model=SessionHistoryDetail)
async def get_session(session_id: str, request: Request) -> SessionHistoryDetail:
    """Rehydrate one terminal session without rerunning its workflow."""
    try:
        return _service(request).get_terminal_session(
            session_id,
            owner_id=request_principal_id(request),
        )
    except SessionHistoryNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session was not found.",
        ) from error
    except SessionHistoryNotReadyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session has not reached a terminal state.",
        ) from error
