"""A2A executor that runs and validates the isolated ADK scoper."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime

from a2a.helpers.proto_helpers import new_data_part, new_task_from_user_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Message
from google.adk.agents import BaseAgent
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types as genai_types
from opentelemetry.trace import Status, StatusCode
from packages.contracts import (
    MAX_SCOPING_REQUEST_BYTES,
    SCOPE_PROPOSAL_ARTIFACT_NAME,
    ArtifactProvenance,
    ScopeProposal,
    ScopeProposalArtifact,
    ScopingRequest,
)
from pydantic import ValidationError

from agentdesk_scoper.settings import ScoperSettings
from agentdesk_scoper.telemetry import TRACER, Outcome, ScoperEvent, ScoperTelemetry


class InvalidScoperOutputError(ValueError):
    """ADK returned output that cannot cross the service boundary."""


class ScoperExecutionError(RuntimeError):
    """The configured agent failed before producing an output."""


class ScoperAgentExecutor(AgentExecutor):
    """Run one bounded ADK task and expose only a typed A2A artifact."""

    def __init__(
        self,
        agent: BaseAgent,
        settings: ScoperSettings,
        telemetry: ScoperTelemetry | None = None,
    ) -> None:
        self._settings = settings
        self._telemetry = telemetry or ScoperTelemetry()
        self._sessions = InMemorySessionService()
        self._runner = Runner(
            app_name="agentdesk_decision_scoper",
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=self._sessions,
            memory_service=InMemoryMemoryService(),
        )
        self._active: dict[str, asyncio.Task[ScopeProposal]] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None or context.task_id is None or context.context_id is None:
            raise ValueError("Scoping tasks require message, task, and context identifiers.")
        await event_queue.enqueue_event(new_task_from_user_message(context.message))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        try:
            raw_request = context.get_user_input()
            if len(raw_request.encode("utf-8")) > MAX_SCOPING_REQUEST_BYTES:
                raise ValueError("Scoping request exceeds the byte limit.")
            request = ScopingRequest.model_validate_json(raw_request)
        except ValidationError, ValueError:
            await updater.reject(
                self._status(context, "Scoping request must match the ScopingRequest schema.")
            )
            return
        if not self._settings.ready:
            await updater.failed(self._status(context, "Decision scoping is not configured."))
            return

        await updater.start_work(self._status(context, "Decision scoping started."))
        self._emit(context, "scoper.request", "started")
        execution = asyncio.create_task(self._produce(context, request))
        self._active[context.task_id] = execution
        try:
            proposal = await execution
        except asyncio.CancelledError:
            self._emit(context, "scoper.request", "cancelled")
            return
        except TimeoutError:
            self._emit(context, "scoper.request", "failed", error_code="timeout")
            await updater.failed(self._status(context, "Decision scoping timed out."))
            return
        except InvalidScoperOutputError:
            self._emit(context, "scoper.request", "failed", error_code="invalid_output")
            await updater.failed(
                self._status(context, "Decision scoping returned an invalid artifact.")
            )
            return
        except Exception:
            self._emit(context, "scoper.request", "failed", error_code="provider_failure")
            await updater.failed(self._status(context, "Decision scoping provider failed."))
            return
        finally:
            self._active.pop(context.task_id, None)

        artifact = ScopeProposalArtifact(
            provenance=ArtifactProvenance(
                producer_agent="decision-scoper",
                remote_task_id=context.task_id,
                created_at=datetime.now(UTC),
            ),
            payload=proposal,
        )
        await updater.add_artifact(
            [new_data_part(artifact.model_dump(mode="json"), media_type="application/json")],
            name=SCOPE_PROPOSAL_ARTIFACT_NAME,
            metadata={"partial": False, "schemaVersion": "1.0"},
            last_chunk=True,
        )
        await updater.complete(self._status(context, "Decision scoping completed."))
        self._emit(context, "scoper.request", "completed")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id is None or context.context_id is None:
            raise ValueError("Cancellation requires task and context identifiers.")
        execution = self._active.get(context.task_id)
        if execution is not None:
            execution.cancel()
            with suppress(asyncio.CancelledError):
                await execution
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel(self._status(context, "Decision scoping cancelled."))
        self._emit(context, "scoper.cancel", "cancelled")

    async def _produce(self, context: RequestContext, request: ScopingRequest) -> ScopeProposal:
        proposal_id = self._proposal_id(context.task_id or "missing")
        command = json.dumps(
            {
                "proposal_id": proposal_id,
                "question": request.question,
                "request": request.model_dump(mode="json"),
            },
            separators=(",", ":"),
        )
        final_error: BaseException | None = None
        for attempt in range(1, self._settings.max_attempts + 1):
            self._emit(context, "scoper.attempt", "started", attempt=attempt)
            try:
                with TRACER.start_as_current_span(
                    "scoper.adk.run",
                    attributes={"scoper.mode": self._settings.mode, "scoper.attempt": attempt},
                    record_exception=False,
                    set_status_on_exception=False,
                ) as span:
                    try:
                        async with asyncio.timeout(self._settings.timeout_seconds):
                            output = await self._run_adk(context, command, attempt)
                        proposal = ScopeProposal.model_validate_json(output)
                    except (ValidationError, ValueError) as error:
                        span.set_status(Status(StatusCode.ERROR))
                        raise InvalidScoperOutputError from error
                if proposal.proposal_id != proposal_id or proposal.question != request.question:
                    raise InvalidScoperOutputError(
                        "Scoper output changed bound request identifiers."
                    )
                self._emit(context, "scoper.attempt", "completed", attempt=attempt)
                return proposal
            except asyncio.CancelledError:
                raise
            except InvalidScoperOutputError:
                raise
            except Exception as error:
                final_error = error
                if attempt == self._settings.max_attempts:
                    break
                await asyncio.sleep(self._settings.retry_delay_seconds)
        if isinstance(final_error, TimeoutError):
            raise final_error
        raise ScoperExecutionError from final_error

    async def _run_adk(self, context: RequestContext, command: str, attempt: int) -> str:
        context_id = context.context_id or "missing"
        user_id = f"A2A_USER_{context_id}"
        session_id = f"{context_id}-attempt-{attempt}"
        await self._sessions.create_session(
            app_name=self._runner.app_name,
            user_id=user_id,
            session_id=session_id,
        )
        output = ""
        async for event in self._runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=command)],
            ),
        ):
            if event.partial or event.content is None:
                continue
            for part in event.content.parts or []:
                if part.text:
                    output = part.text
        if not output:
            raise ScoperExecutionError("ADK execution returned no final text.")
        return output

    def _emit(
        self,
        context: RequestContext,
        event: str,
        outcome: Outcome,
        *,
        attempt: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self._telemetry.emit(
            ScoperEvent(
                event=event,
                mode=self._settings.mode,
                outcome=outcome,
                context_id=context.context_id,
                task_id=context.task_id,
                attempt=attempt,
                error_code=error_code,
            )
        )

    @staticmethod
    def _proposal_id(task_id: str) -> str:
        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:24]
        return f"scope-{digest}"

    @staticmethod
    def _status(context: RequestContext, text: str) -> Message:
        return new_text_message(text, context_id=context.context_id, task_id=context.task_id)
