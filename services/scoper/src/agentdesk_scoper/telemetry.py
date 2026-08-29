"""Content-free telemetry for the isolated scoper."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from opentelemetry import trace

LOGGER = logging.getLogger("agentdesk_scoper")
TRACER = trace.get_tracer("agentdesk.scoper", "0.2.0")
Outcome = Literal["started", "completed", "failed", "cancelled"]


@dataclass(frozen=True)
class ScoperEvent:
    event: str
    mode: str
    outcome: Outcome
    context_id: str | None
    task_id: str | None
    attempt: int | None = None
    error_code: str | None = None
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("duration_ms", "input_tokens", "output_tokens"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} cannot be negative.")


class ScoperTelemetry:
    """Emit only stable fields; this API cannot accept prompts or model output."""

    def emit(self, event: ScoperEvent) -> None:
        payload = {
            "event": event.event,
            "mode": event.mode,
            "outcome": event.outcome,
            "context_id": _safe_id(event.context_id),
            "task_id": _safe_id(event.task_id),
            "attempt": event.attempt,
            "error_code": event.error_code,
            "duration_ms": event.duration_ms,
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
        }
        LOGGER.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _safe_id(value: str | None) -> str | None:
    if value is None:
        return None
    return "".join(character for character in value if character.isprintable())[:128] or None
