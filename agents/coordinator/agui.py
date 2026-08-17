"""AG-UI HTTP/SSE boundary for browser-to-Coordinator interaction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from ag_ui.core import (
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from packages.contracts import AgentDeskViewState

router = APIRouter(prefix="/ag-ui", tags=["ag-ui"])


def _latest_user_text(input_data: RunAgentInput) -> str | None:
    for message in reversed(input_data.messages):
        if message.role == "user" and isinstance(message.content, str):
            text = message.content.strip()
            if text:
                return text
    return None


@router.post("")
async def run_agent(input_data: RunAgentInput, request: Request) -> StreamingResponse:
    """Accept one AG-UI run and stream a deterministic protocol proof."""
    encoder = EventEncoder(accept=request.headers.get("accept"))

    async def events() -> AsyncIterator[str]:
        yield encoder.encode(
            RunStartedEvent(threadId=input_data.thread_id, runId=input_data.run_id)
        )

        question = _latest_user_text(input_data)
        if question is None:
            yield encoder.encode(
                RunErrorEvent(
                    message="A non-empty user message is required.",
                    code="invalid_research_request",
                )
            )
            return

        step_name = "accept-research-request"
        yield encoder.encode(StepStartedEvent(stepName=step_name))
        state = AgentDeskViewState(
            session_id=input_data.run_id,
            question=question,
            status="planning",
            active_step=step_name,
        )
        yield encoder.encode(StateSnapshotEvent(snapshot=state.to_ag_ui()))

        message_id = str(uuid4())
        yield encoder.encode(TextMessageStartEvent(messageId=message_id, role="assistant"))
        yield encoder.encode(
            TextMessageContentEvent(
                messageId=message_id,
                delta="Research request accepted. Planning will begin next.",
            )
        )
        yield encoder.encode(TextMessageEndEvent(messageId=message_id))
        yield encoder.encode(StepFinishedEvent(stepName=step_name))
        yield encoder.encode(
            RunFinishedEvent(
                threadId=input_data.thread_id,
                runId=input_data.run_id,
                result={"sessionId": input_data.run_id},
            )
        )

    return StreamingResponse(events(), media_type=encoder.get_content_type())
