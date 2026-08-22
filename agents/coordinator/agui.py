"""AG-UI HTTP/SSE boundary for browser-to-Coordinator interaction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agents.coordinator.agui_security import request_principal_id, validate_run_input
from agents.coordinator.run_adapter import (
    A2ATaskCommandExecutor,
    CoordinatorRunAdapter,
)
from agents.coordinator.run_tasks import A2ATaskFactory

router = APIRouter(prefix="/ag-ui", tags=["ag-ui"])


async def stream_run_events(
    input_data: RunAgentInput,
    encoder: EventEncoder,
    task_factory: A2ATaskFactory | None = None,
    *,
    run_adapter: CoordinatorRunAdapter | None = None,
    principal_id: str = "local-development",
) -> AsyncIterator[str]:
    """Encode one validated AG-UI run through the Coordinator adapter."""
    if task_factory is not None and run_adapter is not None:
        raise ValueError("Supply either task_factory or run_adapter, not both.")
    if run_adapter is None and task_factory is None:
        raise ValueError("A Coordinator run adapter or A2A task factory is required.")
    if run_adapter is not None:
        adapter = run_adapter
    else:
        assert task_factory is not None
        adapter = CoordinatorRunAdapter(executor=A2ATaskCommandExecutor(task_factory))
    async for event in adapter.stream(input_data, encoder, principal_id=principal_id):
        yield event


@router.post("")
async def run_agent(input_data: RunAgentInput, request: Request) -> StreamingResponse:
    """Accept an official AG-UI run and stream Coordinator protocol events."""
    validate_run_input(input_data)
    principal_id = request_principal_id(request)
    encoder = EventEncoder(accept=request.headers.get("accept", "text/event-stream"))
    adapter = cast(CoordinatorRunAdapter, request.app.state.ag_ui_run_adapter)
    return StreamingResponse(
        stream_run_events(
            input_data,
            encoder,
            run_adapter=adapter,
            principal_id=principal_id,
        ),
        media_type=encoder.get_content_type(),
    )
