"""A2A executor for evidence-bound claim verification."""

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
from a2a.types import Message
from pydantic import ValidationError

from agents.verifier.verification import ClaimVerificationError, ClaimVerifier
from packages.contracts import (
    ArtifactEnvelope,
    ArtifactProvenance,
    EvidenceBundle,
    VerificationReport,
)
from packages.llm import LLMProviderError
from packages.observability import CorrelationIds, observed_request

FINAL_VERIFICATION_ARTIFACT = "verification-report"
LOGGER = logging.getLogger(__name__)


class VerifierAgentExecutor(AgentExecutor):
    """Translate validated verification into a typed A2A task and artifact."""

    def __init__(self, verifier: ClaimVerifier | None = None) -> None:
        self._verifier = verifier

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        with observed_request(LOGGER, "a2a.request", self._log_ids(context)):
            await self._execute(context, event_queue)

    async def _execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None or context.task_id is None or context.context_id is None:
            raise ValueError("Verification tasks require message, task, and context identifiers.")

        await event_queue.enqueue_event(new_task_from_user_message(context.message))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        try:
            evidence_bundle = EvidenceBundle.model_validate_json(context.get_user_input())
        except ValidationError:
            await updater.reject(
                self._status_message(
                    context,
                    "Verification input must be valid JSON matching the EvidenceBundle schema.",
                )
            )
            return

        if self._verifier is None:
            await updater.failed(
                self._status_message(context, "Claim verification is not configured.")
            )
            return

        await updater.start_work(
            self._status_message(context, "Verifying claims against supplied evidence.")
        )
        try:
            report = await self._verifier.verify(evidence_bundle)
        except ClaimVerificationError as error:
            await updater.failed(
                self._status_message(context, f"Claim verification failed ({error.code}).")
            )
            return
        except LLMProviderError:
            await updater.failed(
                self._status_message(context, "The claim verification provider failed.")
            )
            return
        except Exception:
            await updater.failed(
                self._status_message(context, "Claim verification failed unexpectedly.")
            )
            return

        await updater.add_artifact(
            [new_data_part(self._envelope(context, report), media_type="application/json")],
            name=FINAL_VERIFICATION_ARTIFACT,
            metadata={"partial": False, "schemaVersion": "1.0"},
            last_chunk=True,
        )
        await updater.complete(self._status_message(context, "Claim verification completed."))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        with observed_request(LOGGER, "a2a.cancel", self._log_ids(context)):
            await self._cancel(context, event_queue)

    async def _cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id is None or context.context_id is None:
            raise ValueError("Cancellation requires task and context identifiers.")
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel(self._status_message(context, "Verification task cancelled."))

    @staticmethod
    def _log_ids(context: RequestContext) -> CorrelationIds:
        return CorrelationIds(
            context_id=context.context_id,
            correlation_id=context.context_id,
            agent="verifier",
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
    def _envelope(context: RequestContext, report: VerificationReport) -> dict[str, object]:
        if context.task_id is None:  # pragma: no cover - guarded by execute
            raise ValueError("Artifact provenance requires a task ID.")
        envelope = ArtifactEnvelope[VerificationReport](
            provenance=ArtifactProvenance(
                producer_agent="verifier",
                remote_task_id=context.task_id,
                created_at=datetime.now(UTC),
            ),
            payload=report,
        )
        return envelope.model_dump(mode="json")
