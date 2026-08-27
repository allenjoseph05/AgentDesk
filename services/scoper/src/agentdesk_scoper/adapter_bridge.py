"""AgentDesk A2A transport adapter around the isolated ADK runner.

This is a compatibility probe, not a production scoper route. It proves that ADK
can own agent execution while AgentDesk retains its validated HTTP+JSON boundary.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from a2a.helpers.proto_helpers import new_data_part, new_task_from_user_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_rest_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Message
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol
from fastapi import FastAPI
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types as genai_types

from agentdesk_scoper.fixture_agent import FixtureScoperAgent

DEFAULT_BASE_URL = "http://127.0.0.1:8011"
FINAL_ARTIFACT = "scope-proposal"


def create_agent_card(base_url: str) -> AgentCard:
    """Describe the HTTP+JSON interface required by the AgentDesk registry."""
    return AgentCard(
        name="AgentDesk ADK scoper adapter probe",
        description="Proves ADK execution behind AgentDesk's established A2A transport.",
        supported_interfaces=[
            AgentInterface(
                url=base_url.rstrip("/"),
                protocol_binding=TransportProtocol.HTTP_JSON,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id="decision-scoping",
                name="Decision scoping",
                description="Propose bounded fields for clarifying a comparison question.",
                tags=["decision", "scoping", "intake"],
            )
        ],
    )


class AdkScoperAdapterExecutor(AgentExecutor):
    """Project deterministic ADK output through AgentDesk's A2A conventions."""

    def __init__(self, agent: FixtureScoperAgent, *, timeout_seconds: float) -> None:
        self._session_service = InMemorySessionService()
        self._runner = Runner(
            app_name="agentdesk_scoper_compatibility",
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=self._session_service,
            memory_service=InMemoryMemoryService(),
        )
        self._timeout_seconds = timeout_seconds
        self._active: dict[str, asyncio.Task[str]] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None or context.task_id is None or context.context_id is None:
            raise ValueError("Scoping tasks require message, task, and context identifiers.")
        await event_queue.enqueue_event(new_task_from_user_message(context.message))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.start_work(self._status_message(context, "Decision-scoping task accepted."))

        execution = asyncio.create_task(self._run_adk(context))
        self._active[context.task_id] = execution
        try:
            output = await asyncio.wait_for(execution, timeout=self._timeout_seconds)
        except TimeoutError:
            await updater.failed(self._status_message(context, "Decision scoping timed out."))
            return
        except asyncio.CancelledError:
            return
        finally:
            self._active.pop(context.task_id, None)

        try:
            proposal = json.loads(output)
        except json.JSONDecodeError:
            await updater.failed(
                self._status_message(context, "Decision scoping returned an invalid artifact.")
            )
            return
        if not isinstance(proposal, dict):
            await updater.failed(
                self._status_message(context, "Decision scoping returned an invalid artifact.")
            )
            return

        await updater.add_artifact(
            [new_data_part(proposal, media_type="application/json")],
            name=FINAL_ARTIFACT,
            metadata={"schemaVersion": proposal.get("schema_version", "unknown")},
            last_chunk=True,
        )
        await updater.complete(self._status_message(context, "Decision scoping completed."))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id is None or context.context_id is None:
            raise ValueError("Cancellation requires task and context identifiers.")
        execution = self._active.get(context.task_id)
        if execution is not None:
            execution.cancel()
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel(self._status_message(context, "Decision scoping cancelled."))

    async def _run_adk(self, context: RequestContext) -> str:
        if context.context_id is None:
            raise ValueError("ADK execution requires an A2A context identifier.")
        user_id = f"A2A_USER_{context.context_id}"
        session = await self._session_service.get_session(
            app_name=self._runner.app_name,
            user_id=user_id,
            session_id=context.context_id,
        )
        if session is None:
            await self._session_service.create_session(
                app_name=self._runner.app_name,
                user_id=user_id,
                session_id=context.context_id,
            )

        output = ""
        async for event in self._runner.run_async(
            user_id=user_id,
            session_id=context.context_id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=context.get_user_input())],
            ),
        ):
            if event.content is None:
                continue
            for part in event.content.parts or []:
                if part.text:
                    output = part.text
        if not output:
            raise ValueError("ADK execution returned no text output.")
        return output

    @staticmethod
    def _status_message(context: RequestContext, text: str) -> Message:
        return new_text_message(
            text,
            context_id=context.context_id,
            task_id=context.task_id,
        )


def create_adapter_app(
    base_url: str = DEFAULT_BASE_URL,
    *,
    delay_seconds: float = 0.0,
    malformed_output: bool = False,
    timeout_seconds: float = 2.0,
) -> FastAPI:
    """Create the isolated AgentDesk-adapter compatibility application."""
    card = create_agent_card(base_url)
    executor = AdkScoperAdapterExecutor(
        FixtureScoperAgent(
            name="decision_scoper",
            description="Deterministic ADK decision-scoping compatibility agent.",
            delay_seconds=delay_seconds,
            malformed_output=malformed_output,
        ),
        timeout_seconds=timeout_seconds,
    )
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await request_handler.aclose()

    application = FastAPI(title="AgentDesk scoper adapter compatibility", lifespan=lifespan)
    add_a2a_routes_to_fastapi(
        application,
        agent_card_routes=create_agent_card_routes(card),
        rest_routes=create_rest_routes(request_handler),
    )
    return application


app = create_adapter_app(
    os.getenv("SCOPER_COMPAT_URL", DEFAULT_BASE_URL),
    delay_seconds=float(os.getenv("SCOPER_FIXTURE_DELAY_SECONDS", "0")),
    malformed_output=os.getenv("SCOPER_FIXTURE_MALFORMED", "0") == "1",
    timeout_seconds=float(os.getenv("SCOPER_COMPAT_TIMEOUT_SECONDS", "2")),
)
