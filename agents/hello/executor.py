"""Deterministic executor for the standalone hello agent."""

from a2a.helpers.proto_helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue


class HelloAgentExecutor(AgentExecutor):
    """Produce one immediate, typed A2A message without an LLM."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        name = context.get_user_input().strip() or "world"
        response = new_text_message(
            f"Hello, {name}!",
            context_id=context.context_id,
            task_id=context.task_id,
        )
        await event_queue.enqueue_event(response)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("The hello agent completes immediately and cannot be cancelled.")
