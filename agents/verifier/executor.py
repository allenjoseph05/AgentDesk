"""A2A executor boundary for the Verifier Agent service shell."""

from a2a.helpers.proto_helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue


class VerifierAgentExecutor(AgentExecutor):
    """Keep the A2A service operational until verification execution is added."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(
            new_text_message(
                "Fact verification is not configured yet.",
                context_id=context.context_id,
                task_id=context.task_id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("The Verifier Agent has no cancellable task yet.")
