"""A2A executor for evidence-bound decision analysis."""

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

from agents.analyst.analysis import (
    DecisionAnalysisError,
    DecisionAnalyzer,
    RecommendationChallengeError,
)
from packages.contracts import (
    AnalysisRequest,
    ArtifactEnvelope,
    ArtifactProvenance,
    DecisionAnalysis,
    RecommendationChallenge,
)
from packages.llm import LLMProviderError
from packages.observability import CorrelationIds, observed_request

FINAL_ANALYSIS_ARTIFACT = "decision-analysis"
FINAL_CHALLENGE_ARTIFACT = "recommendation-challenge"
LOGGER = logging.getLogger(__name__)


class AnalystAgentExecutor(AgentExecutor):
    """Translate validated analysis into a typed A2A task and artifact."""

    def __init__(self, analyzer: DecisionAnalyzer | None = None) -> None:
        self._analyzer = analyzer

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        with observed_request(LOGGER, "a2a.request", self._log_ids(context)):
            await self._execute(context, event_queue)

    async def _execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None or context.task_id is None or context.context_id is None:
            raise ValueError("Analysis tasks require message, task, and context identifiers.")

        await event_queue.enqueue_event(new_task_from_user_message(context.message))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        try:
            request = AnalysisRequest.model_validate_json(context.get_user_input())
        except ValidationError:
            await updater.reject(
                self._status_message(
                    context,
                    "Analysis request must be valid JSON matching the AnalysisRequest schema.",
                )
            )
            return

        if self._analyzer is None:
            await updater.failed(
                self._status_message(context, "Decision analysis is not configured.")
            )
            return

        challenge_mode = request.mode == "challenge_current_recommendation"
        working_message = (
            "Challenging the current recommendation using supplied evidence."
            if challenge_mode
            else "Analyzing options against supplied evidence."
        )
        await updater.start_work(self._status_message(context, working_message))
        try:
            output = (
                await self._analyzer.challenge(request)
                if challenge_mode
                else await self._analyzer.analyze(request)
            )
        except (DecisionAnalysisError, RecommendationChallengeError) as error:
            await updater.failed(
                self._status_message(context, f"Analyst output failed ({error.code}).")
            )
            return
        except LLMProviderError:
            await updater.failed(
                self._status_message(context, "The Analyst provider failed.")
            )
            return
        except Exception:
            await updater.failed(
                self._status_message(context, "Analysis failed unexpectedly.")
            )
            return

        await updater.add_artifact(
            [new_data_part(self._envelope(context, output), media_type="application/json")],
            name=FINAL_CHALLENGE_ARTIFACT if challenge_mode else FINAL_ANALYSIS_ARTIFACT,
            metadata={"partial": False, "schemaVersion": "1.0"},
            last_chunk=True,
        )
        completion_message = (
            "Recommendation challenge completed."
            if challenge_mode
            else "Decision analysis completed."
        )
        await updater.complete(self._status_message(context, completion_message))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        with observed_request(LOGGER, "a2a.cancel", self._log_ids(context)):
            await self._cancel(context, event_queue)

    async def _cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id is None or context.context_id is None:
            raise ValueError("Cancellation requires task and context identifiers.")
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel(self._status_message(context, "Analysis task cancelled."))

    @staticmethod
    def _log_ids(context: RequestContext) -> CorrelationIds:
        return CorrelationIds(
            context_id=context.context_id,
            correlation_id=context.context_id,
            agent="analyst",
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
    def _envelope(
        context: RequestContext,
        output: DecisionAnalysis | RecommendationChallenge,
    ) -> dict[str, object]:
        if context.task_id is None:  # pragma: no cover - guarded by execute
            raise ValueError("Artifact provenance requires a task ID.")
        provenance = ArtifactProvenance(
            producer_agent="analyst",
            remote_task_id=context.task_id,
            created_at=datetime.now(UTC),
        )
        if isinstance(output, DecisionAnalysis):
            return ArtifactEnvelope[DecisionAnalysis](
                provenance=provenance,
                payload=output,
            ).model_dump(mode="json")
        return ArtifactEnvelope[RecommendationChallenge](
            provenance=provenance,
            payload=output,
        ).model_dump(mode="json")
