"""A2A executor for evidence-bound decision analysis."""

from datetime import UTC, datetime

from a2a.helpers.proto_helpers import (
    new_data_part,
    new_task_from_user_message,
    new_text_message,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from pydantic import ValidationError

from agents.analyst.analysis import DecisionAnalysisError, DecisionAnalyzer
from packages.contracts import (
    AnalysisRequest,
    ArtifactEnvelope,
    ArtifactProvenance,
    DecisionAnalysis,
)
from packages.llm import LLMProviderError

FINAL_ANALYSIS_ARTIFACT = "decision-analysis"


class AnalystAgentExecutor(AgentExecutor):
    """Translate validated analysis into a typed A2A task and artifact."""

    def __init__(self, analyzer: DecisionAnalyzer | None = None) -> None:
        self._analyzer = analyzer

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
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

        await updater.start_work(
            self._status_message(context, "Analyzing options against supplied evidence.")
        )
        try:
            analysis = await self._analyzer.analyze(request)
        except DecisionAnalysisError as error:
            await updater.failed(
                self._status_message(context, f"Decision analysis failed ({error.code}).")
            )
            return
        except LLMProviderError:
            await updater.failed(
                self._status_message(context, "The decision analysis provider failed.")
            )
            return
        except Exception:
            await updater.failed(
                self._status_message(context, "Decision analysis failed unexpectedly.")
            )
            return

        await updater.add_artifact(
            [new_data_part(self._envelope(context, analysis), media_type="application/json")],
            name=FINAL_ANALYSIS_ARTIFACT,
            metadata={"partial": False, "schemaVersion": "1.0"},
            last_chunk=True,
        )
        await updater.complete(self._status_message(context, "Decision analysis completed."))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id is None or context.context_id is None:
            raise ValueError("Cancellation requires task and context identifiers.")
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel(self._status_message(context, "Analysis task cancelled."))

    @staticmethod
    def _status_message(context: RequestContext, text: str):
        return new_text_message(
            text,
            context_id=context.context_id,
            task_id=context.task_id,
        )

    @staticmethod
    def _envelope(context: RequestContext, analysis: DecisionAnalysis) -> dict[str, object]:
        if context.task_id is None:  # pragma: no cover - guarded by execute
            raise ValueError("Artifact provenance requires a task ID.")
        envelope = ArtifactEnvelope[DecisionAnalysis](
            provenance=ArtifactProvenance(
                producer_agent="analyst",
                remote_task_id=context.task_id,
                created_at=datetime.now(UTC),
            ),
            payload=analysis,
        )
        return envelope.model_dump(mode="json")
