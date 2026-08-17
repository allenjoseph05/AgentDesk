"""A2A executor boundary for the Analyst Agent service shell."""

from a2a.helpers.proto_helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from pydantic import ValidationError

from packages.contracts import AnalysisRequest


class AnalystAgentExecutor(AgentExecutor):
    """Validate evidence-bound requests until decision analysis is implemented."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        try:
            AnalysisRequest.model_validate_json(context.get_user_input())
        except ValidationError:
            response_text = (
                "Analysis request must be valid JSON matching the AnalysisRequest schema."
            )
        else:
            response_text = "Structured evidence accepted; analysis is not configured yet."

        await event_queue.enqueue_event(
            new_text_message(
                response_text,
                context_id=context.context_id,
                task_id=context.task_id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("The Analyst Agent has no cancellable task yet.")
