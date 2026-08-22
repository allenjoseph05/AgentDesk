"""OpenTelemetry span creation and cross-service propagation tests."""

from __future__ import annotations

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from packages.observability import (
    CorrelationIds,
    TracingSettings,
    configure_tracing,
    current_trace_ids,
    inject_trace_context,
    traced_client_call,
    traced_request,
)


def test_demo_request_keeps_one_trace_across_coordinator_and_specialist() -> None:
    disabled = configure_tracing(
        "disabled-local-service",
        settings=TracingSettings(enabled=False),
    )
    assert disabled.enabled is False
    assert inject_trace_context() == {}

    exporter = InMemorySpanExporter()
    runtime = configure_tracing(
        "agentdesk-trace-test",
        settings=TracingSettings(enabled=True),
        exporter=exporter,
    )
    coordinator_ids = CorrelationIds(
        session_id="session-1",
        context_id="thread-1",
        correlation_id="run-1",
        action_id="action-1",
        agent="coordinator",
    )

    with traced_request("coordinator.request", coordinator_ids):
        root_trace_id, root_span_id = current_trace_ids()
        with traced_client_call(
            "a2a.send",
            CorrelationIds(agent="researcher"),
        ):
            _, client_span_id = current_trace_ids()
            carrier = inject_trace_context()

        with traced_request(
            "a2a.receive",
            CorrelationIds(
                context_id="research-context-1",
                agent="researcher",
                remote_task_id="research-task-1",
            ),
            carrier=carrier,
        ):
            specialist_trace_id, _ = current_trace_ids()

    with traced_request(
        "a2a.invalid_receive",
        CorrelationIds(agent="researcher"),
        carrier={
            "traceparent": "not-a-valid-traceparent",
            "authorization": "Bearer must-not-be-read",
        },
    ):
        invalid_trace_id, invalid_span_id = current_trace_ids()

    spans = {span.name: span for span in exporter.get_finished_spans()}
    root = spans["coordinator.request"]
    client = spans["a2a.send"]
    specialist = spans["a2a.receive"]
    assert root_trace_id == specialist_trace_id
    assert {span.context.trace_id for span in (root, client, specialist)} == {root.context.trace_id}
    assert client.parent is not None and client.parent.span_id == root.context.span_id
    assert specialist.parent is not None
    assert specialist.parent.span_id == client.context.span_id
    assert root_span_id == f"{root.context.span_id:016x}"
    assert client_span_id == f"{client.context.span_id:016x}"
    assert client.kind is SpanKind.CLIENT
    assert specialist.kind is SpanKind.SERVER
    assert root.attributes is not None
    assert specialist.attributes is not None
    assert root.attributes["agentdesk.session.id"] == "session-1"
    assert specialist.attributes["agentdesk.remote_task.id"] == "research-task-1"
    assert set(carrier) <= {"traceparent", "tracestate"}
    assert invalid_trace_id is not None and invalid_trace_id != root_trace_id
    assert invalid_span_id is not None
    invalid_attributes = spans["a2a.invalid_receive"].attributes
    assert invalid_attributes is not None
    assert "authorization" not in invalid_attributes

    configure_tracing("disabled-again", settings=TracingSettings(enabled=False))
    exported_count = len(exporter.get_finished_spans())
    with traced_request("coordinator.disabled", coordinator_ids):
        assert current_trace_ids() == (None, None)
        assert inject_trace_context() == {}
    assert len(exporter.get_finished_spans()) == exported_count
    runtime.shutdown()
