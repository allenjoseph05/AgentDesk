"""OpenTelemetry tracing and W3C context propagation for AgentDesk services."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from packages.observability.logging import CorrelationIds

_TRACER = trace.get_tracer("agentdesk", "0.1.0")
_PROPAGATOR: Final = TraceContextTextMapPropagator()
_SPAN_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")
_MAX_ATTRIBUTE_LENGTH = 255
_DEFAULT_OTLP_ENDPOINT = "http://127.0.0.1:4318/v1/traces"
_tracing_enabled = False


@dataclass(frozen=True)
class TracingSettings:
    """Runtime tracing configuration; local development is disabled by default."""

    enabled: bool = False
    endpoint: str = _DEFAULT_OTLP_ENDPOINT
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.enabled and not self.endpoint.strip():
            raise ValueError("Enabled tracing requires an OTLP traces endpoint.")
        if self.timeout_seconds <= 0:
            raise ValueError("Tracing export timeout must be positive.")

    @classmethod
    def from_environment(cls) -> TracingSettings:
        return cls(
            enabled=_environment_flag("AGENTDESK_TRACING_ENABLED", default=False),
            endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                _DEFAULT_OTLP_ENDPOINT,
            ),
            timeout_seconds=float(os.getenv("AGENTDESK_TRACING_TIMEOUT_SECONDS", "10")),
        )


@dataclass
class TracingRuntime:
    """Configured provider lifecycle owned by one independently run service."""

    provider: TracerProvider | None = None

    @property
    def enabled(self) -> bool:
        return self.provider is not None

    def shutdown(self) -> None:
        if self.provider is not None:
            self.provider.shutdown()


def configure_tracing(
    service_name: str,
    *,
    settings: TracingSettings | None = None,
    exporter: SpanExporter | None = None,
) -> TracingRuntime:
    """Configure one service provider, or retain the no-op API in local mode."""
    global _tracing_enabled

    resolved = settings or TracingSettings.from_environment()
    if not resolved.enabled:
        _tracing_enabled = False
        return TracingRuntime()
    if not service_name.strip():
        raise ValueError("Tracing service name cannot be blank.")

    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: service_name.strip()}),
        shutdown_on_exit=False,
    )
    span_exporter = exporter or OTLPSpanExporter(
        endpoint=resolved.endpoint,
        timeout=resolved.timeout_seconds,
    )
    processor = (
        SimpleSpanProcessor(span_exporter)
        if exporter is not None
        else BatchSpanProcessor(span_exporter)
    )
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _tracing_enabled = True
    return TracingRuntime(provider=provider)


@contextmanager
def traced_request(
    name: str,
    ids: CorrelationIds,
    *,
    carrier: Mapping[str, object] | None = None,
) -> Iterator[Span]:
    """Create a server/root span using an optional remote W3C parent context."""
    parent = extract_trace_context(carrier) if carrier is not None else None
    with _start_span(name, ids, kind=SpanKind.SERVER, parent=parent) as span:
        yield span


@contextmanager
def traced_client_call(name: str, ids: CorrelationIds) -> Iterator[Span]:
    """Create a client span for one Coordinator-to-specialist operation."""
    with _start_span(name, ids, kind=SpanKind.CLIENT) as span:
        yield span


def inject_trace_context() -> dict[str, str]:
    """Serialize only W3C trace fields from the current span for A2A metadata."""
    if not _tracing_enabled:
        return {}
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    return carrier


def extract_trace_context(carrier: Mapping[str, object] | None) -> Context:
    """Safely extract allowlisted W3C fields from untrusted request metadata."""
    if carrier is None:
        return Context()
    trace_carrier = {
        key: value
        for key in ("traceparent", "tracestate")
        if isinstance((value := carrier.get(key)), str)
    }
    return _PROPAGATOR.extract(carrier=trace_carrier)


def current_trace_ids() -> tuple[str | None, str | None]:
    """Return active lowercase hexadecimal identifiers for log correlation."""
    if not _tracing_enabled:
        return None, None
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None, None
    return f"{span_context.trace_id:032x}", f"{span_context.span_id:016x}"


@contextmanager
def _start_span(
    name: str,
    ids: CorrelationIds,
    *,
    kind: SpanKind,
    parent: Context | None = None,
) -> Iterator[Span]:
    if not _SPAN_NAME_PATTERN.fullmatch(name):
        raise ValueError("Trace span names must be stable dotted identifiers.")
    if not _tracing_enabled:
        yield trace.INVALID_SPAN
        return
    with _TRACER.start_as_current_span(
        name,
        context=parent,
        kind=kind,
        attributes=_span_attributes(ids),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException:
            span.set_status(Status(StatusCode.ERROR))
            raise


def _span_attributes(ids: CorrelationIds) -> dict[str, str]:
    values = {
        "agentdesk.session.id": ids.session_id,
        "agentdesk.context.id": ids.context_id,
        "agentdesk.correlation.id": ids.correlation_id,
        "agentdesk.action.id": ids.action_id,
        "agentdesk.agent.id": ids.agent,
        "agentdesk.remote_task.id": ids.remote_task_id,
    }
    return {
        key: safe_value
        for key, value in values.items()
        if (safe_value := _safe_attribute(value)) is not None
    }


def _safe_attribute(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(character for character in value.strip() if character.isprintable())
    return normalized[:_MAX_ATTRIBUTE_LENGTH] or None


def _environment_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean flag.")
