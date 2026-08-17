"""AG-UI HTTP/SSE boundary for browser-to-Coordinator interaction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
from pydantic import ValidationError

from packages.contracts import AgentDeskAction, AgentDeskViewState
from packages.contracts.agui import StartResearchAction

router = APIRouter(prefix="/ag-ui", tags=["ag-ui"])


def _latest_user_text(input_data: RunAgentInput) -> str | None:
    for message in reversed(input_data.messages):
        if message.role == "user" and isinstance(message.content, str):
            text = message.content.strip()
            if text:
                return text
    return None


def _start_action(input_data: RunAgentInput) -> StartResearchAction:
    forwarded_props = input_data.forwarded_props
    if not isinstance(forwarded_props, dict) or "agentdesk" not in forwarded_props:
        raise ValueError("forwardedProps.agentdesk is required.")
    action = AgentDeskAction.model_validate(forwarded_props["agentdesk"]).root
    if not isinstance(action, StartResearchAction):
        raise ValueError("This endpoint slice currently accepts start_research actions only.")
    return action


@router.post("")
async def run_agent(input_data: RunAgentInput, request: Request) -> StreamingResponse:
    """Accept one AG-UI run and stream a deterministic protocol proof."""
    encoder = EventEncoder(accept=request.headers.get("accept"))

    async def events() -> AsyncIterator[str]:
        yield encoder.encode(
            RunStartedEvent(threadId=input_data.thread_id, runId=input_data.run_id)
        )

        try:
            action = _start_action(input_data)
        except (ValidationError, ValueError):
            yield encoder.encode(
                RunErrorEvent(
                    message="A valid AgentDesk action envelope is required.",
                    code="invalid_agentdesk_action",
                )
            )
            return

        question = _latest_user_text(input_data)
        if question != action.payload.question:
            yield encoder.encode(
                RunErrorEvent(
                    message="The user message and structured action question must match.",
                    code="action_message_mismatch",
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
            last_updated_at=datetime.now(UTC),
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
                result={"sessionId": input_data.run_id, "actionId": action.action_id},
            )
        )

    return StreamingResponse(events(), media_type=encoder.get_content_type())
