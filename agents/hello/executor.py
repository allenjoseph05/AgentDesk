"""Deterministic executor for the standalone hello agent."""

import asyncio

from a2a.helpers.proto_helpers import (
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState

STREAM_PREFIX = "stream:"
STREAM_STEP_DELAY_SECONDS = 0.15


class HelloAgentExecutor(AgentExecutor):
    """Produce one immediate, typed A2A message without an LLM."""

    def __init__(self, stream_step_delay_seconds: float = STREAM_STEP_DELAY_SECONDS) -> None:
        self._stream_step_delay_seconds = stream_step_delay_seconds

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_input = context.get_user_input().strip()
        if user_input.casefold().startswith(STREAM_PREFIX):
            await self._execute_streaming_task(context, event_queue, user_input)
            return

        name = user_input or "world"
        response = new_text_message(
            f"Hello, {name}!",
            context_id=context.context_id,
            task_id=context.task_id,
        )
        await event_queue.enqueue_event(response)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id is None or context.context_id is None:
            raise ValueError("Cancellation requires task and context identifiers.")

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel(
            new_text_message(
                "Greeting task cancelled.",
                context_id=context.context_id,
                task_id=context.task_id,
            )
        )

    async def _execute_streaming_task(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        user_input: str,
    ) -> None:
        if context.message is None or context.task_id is None or context.context_id is None:
            raise ValueError("Streaming tasks require a complete A2A request context.")

        name = user_input[len(STREAM_PREFIX) :].strip() or "world"
        await event_queue.enqueue_event(new_task_from_user_message(context.message))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        await updater.start_work(self._status_message(context, f"Preparing greeting for {name}."))
        await asyncio.sleep(self._stream_step_delay_seconds)
        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            message=self._status_message(context, f"Greeting ready for {name}."),
        )
        await asyncio.sleep(self._stream_step_delay_seconds)
        await updater.add_artifact(
            [new_text_part(f"Hello, {name}!")],
            name="greeting",
            last_chunk=True,
        )
        await updater.complete(self._status_message(context, "Greeting task completed."))

    @staticmethod
    def _status_message(context: RequestContext, text: str):
        return new_text_message(
            text,
            context_id=context.context_id,
            task_id=context.task_id,
        )
