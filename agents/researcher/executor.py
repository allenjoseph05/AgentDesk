"""A2A executor for streamed research evidence synthesis."""

import logging
from datetime import UTC, datetime

from a2a.helpers.proto_helpers import (
    new_data_part,
    new_task_from_user_message,
    new_text_message,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState
from pydantic import ValidationError

from agents.researcher.synthesis import (
    ResearchProgress,
    ResearchSynthesisError,
    ResearchSynthesizer,
)
from agents.researcher.tools import ResearchToolError
from packages.contracts import ArtifactEnvelope, ArtifactProvenance, EvidenceBundle, ResearchRequest
from packages.limits import LimitExceededError, limit_status_message
from packages.llm import LLMProviderError
from packages.observability import CorrelationIds, observed_request, traced_request

PARTIAL_SOURCES_ARTIFACT = "research-sources"
FINAL_EVIDENCE_ARTIFACT = "evidence-bundle"
LOGGER = logging.getLogger(__name__)


class ResearchAgentExecutor(AgentExecutor):
    """Translate synthesis phases and outputs into typed A2A task events."""

    def __init__(self, synthesizer: ResearchSynthesizer | None = None) -> None:
        self._synthesizer = synthesizer

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        ids = self._log_ids(context)
        with traced_request("a2a.receive", ids, carrier=context.metadata):
            with observed_request(LOGGER, "a2a.request", ids):
                await self._execute(context, event_queue)

    async def _execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None or context.task_id is None or context.context_id is None:
            raise ValueError("Research tasks require message, task, and context identifiers.")

        await event_queue.enqueue_event(new_task_from_user_message(context.message))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        try:
            request = ResearchRequest.model_validate_json(context.get_user_input())
        except ValidationError:
            await updater.reject(
                self._status_message(
                    context,
                    "Research request must be valid JSON matching the ResearchRequest schema.",
                )
            )
            return

        if self._synthesizer is None:
            await updater.failed(
                self._status_message(context, "Research synthesis is not configured.")
            )
            return

        async def report(progress: ResearchProgress) -> None:
            message = self._status_message(context, progress.message)
            if progress.phase == "searching":
                await updater.start_work(message)
            else:
                await updater.update_status(TaskState.TASK_STATE_WORKING, message=message)
            if progress.phase == "synthesizing":
                await updater.add_artifact(
                    [
                        new_data_part(
                            {
                                "schema_version": "1.0",
                                "phase": "sources_collected",
                                "source_ids": progress.source_ids,
                                "failed_source_ids": progress.failed_source_ids,
                            },
                            media_type="application/json",
                        )
                    ],
                    name=PARTIAL_SOURCES_ARTIFACT,
                    metadata={"partial": True, "schemaVersion": "1.0"},
                    last_chunk=True,
                )

        try:
            bundle = await self._synthesizer.synthesize(request, on_progress=report)
        except LimitExceededError as error:
            await updater.failed(self._status_message(context, limit_status_message(error)))
            return
        except ResearchToolError as error:
            await updater.failed(
                self._status_message(
                    context,
                    f"Research tool failed ({error.failure.code}): {error.failure.message}",
                )
            )
            return
        except ResearchSynthesisError as error:
            await updater.failed(
                self._status_message(context, f"Research synthesis failed ({error.code}).")
            )
            return
        except LLMProviderError:
            await updater.failed(
                self._status_message(context, "The evidence synthesis provider failed.")
            )
            return
        except Exception:
            await updater.failed(self._status_message(context, "Research failed unexpectedly."))
            return

        await updater.add_artifact(
            [new_data_part(self._envelope(context, bundle), media_type="application/json")],
            name=FINAL_EVIDENCE_ARTIFACT,
            metadata={"partial": False, "schemaVersion": "1.0"},
            last_chunk=True,
        )
        await updater.complete(self._status_message(context, "Evidence synthesis completed."))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        ids = self._log_ids(context)
        with traced_request("a2a.cancel", ids, carrier=context.metadata):
            with observed_request(LOGGER, "a2a.cancel", ids):
                await self._cancel(context, event_queue)

    async def _cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id is None or context.context_id is None:
            raise ValueError("Cancellation requires task and context identifiers.")
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel(self._status_message(context, "Research task cancelled."))

    @staticmethod
    def _log_ids(context: RequestContext) -> CorrelationIds:
        return CorrelationIds(
            context_id=context.context_id,
            correlation_id=context.context_id,
            agent="researcher",
            remote_task_id=context.task_id,
        )

    @staticmethod
    def _status_message(context: RequestContext, text: str) -> Message:
        return new_text_message(
            text,
            context_id=context.context_id,
            task_id=context.task_id,
        )

    @staticmethod
    def _envelope(context: RequestContext, bundle: EvidenceBundle) -> dict[str, object]:
        if context.task_id is None:  # pragma: no cover - guarded by execute
            raise ValueError("Artifact provenance requires a task ID.")
        envelope = ArtifactEnvelope[EvidenceBundle](
            provenance=ArtifactProvenance(
                producer_agent="researcher",
                remote_task_id=context.task_id,
                created_at=datetime.now(UTC),
            ),
            payload=bundle,
        )
        return envelope.model_dump(mode="json")
