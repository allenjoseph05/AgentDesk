"""Safe structured logging with request-scoped correlation identifiers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

_EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")
_MAX_IDENTIFIER_LENGTH = 255
_HANDLER_NAME = "agentdesk-structured-events"


@dataclass(frozen=True)
class CorrelationIds:
    """Identifiers that join one request across AgentDesk protocol boundaries."""

    session_id: str | None = None
    context_id: str | None = None
    correlation_id: str | None = None
    agent: str | None = None
    remote_task_id: str | None = None
    action_id: str | None = None

    def merged(self, other: CorrelationIds) -> CorrelationIds:
        """Return a child scope, retaining parent values omitted by the child."""
        return replace(
            self,
            **{
                name: value
                for name, value in vars(other).items()
                if value is not None
            },
        )


_correlation_ids: ContextVar[CorrelationIds | None] = ContextVar(
    "agentdesk_correlation_ids",
    default=None,
)


@contextmanager
def correlation_scope(ids: CorrelationIds) -> Iterator[None]:
    """Bind correlation identifiers for logs emitted by nested async work."""
    token: Token[CorrelationIds | None] = _correlation_ids.set(
        (_correlation_ids.get() or CorrelationIds()).merged(ids)
    )
    try:
        yield
    finally:
        _correlation_ids.reset(token)


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    ids: CorrelationIds | None = None,
    outcome: Literal["started", "completed", "failed", "cancelled"] | None = None,
    error_code: str | None = None,
) -> None:
    """Emit one JSON event from a deliberately small, non-sensitive schema.

    Raw requests, headers, prompts, artifacts, and exception messages cannot be
    supplied to this API. Identifier values are normalized to prevent log
    injection and bounded to keep hostile remote identifiers from bloating logs.
    """
    if not _EVENT_PATTERN.fullmatch(event):
        raise ValueError("Structured log event names must be stable dotted identifiers.")

    # Some ASGI logging configurations disable loggers that already existed at
    # startup. Request events must remain observable after those configurations
    # are applied.
    logger.disabled = False
    correlation = _correlation_ids.get() or CorrelationIds()
    if ids is not None:
        correlation = correlation.merged(ids)
    # Imported lazily to keep the logging module usable during tracing setup.
    from packages.observability.tracing import current_trace_ids

    trace_id, span_id = current_trace_ids()
    payload: dict[str, str | None] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": logging.getLevelName(level).lower(),
        "event": event,
        "session_id": _safe_identifier(correlation.session_id),
        "context_id": _safe_identifier(correlation.context_id),
        "correlation_id": _safe_identifier(correlation.correlation_id),
        "action_id": _safe_identifier(correlation.action_id),
        "agent": _safe_identifier(correlation.agent),
        "remote_task_id": _safe_identifier(correlation.remote_task_id),
        "outcome": outcome,
        "error_code": _safe_identifier(error_code),
        "trace_id": trace_id,
        "span_id": span_id,
    }
    logger.log(level, json.dumps(payload, separators=(",", ":"), sort_keys=True))


def configure_structured_logging(*, level: int = logging.INFO) -> None:
    """Make AgentDesk event records visible without depending on server formatters."""
    logger = logging.getLogger("agents")
    logger.setLevel(level)
    if any(handler.get_name() == _HANDLER_NAME for handler in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


@contextmanager
def observed_request(
    logger: logging.Logger,
    event: str,
    ids: CorrelationIds,
) -> Iterator[None]:
    """Log safe start and terminal events around one handled request."""
    with correlation_scope(ids):
        log_event(logger, event, outcome="started")
        try:
            yield
        except asyncio.CancelledError:
            log_event(logger, event, level=logging.WARNING, outcome="cancelled")
            raise
        except Exception:
            log_event(
                logger,
                event,
                level=logging.ERROR,
                outcome="failed",
                error_code="unhandled_exception",
            )
            raise
        else:
            log_event(logger, event, outcome="completed")


def _safe_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(character for character in value.strip() if character.isprintable())
    return normalized[:_MAX_IDENTIFIER_LENGTH] or None
