"""Bounded, fail-closed controls for the browser-facing AG-UI boundary."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from ag_ui.core import RunAgentInput
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from packages.observability import CorrelationIds, log_event

MAX_AG_UI_REQUEST_BYTES = 256 * 1024
MAX_AG_UI_MESSAGES = 50
MAX_AG_UI_MESSAGE_BYTES = 16 * 1024
MAX_AG_UI_TRANSCRIPT_BYTES = 64 * 1024
MAX_AG_UI_STATE_BYTES = 256 * 1024
MAX_AG_UI_PATCH_BYTES = 128 * 1024
MAX_AG_UI_FORWARDED_PROPS_BYTES = 32 * 1024
MAX_AG_UI_IDENTIFIER_LENGTH = 255

CORRELATION_HEADER = "x-agentdesk-correlation-id"
LOCAL_DEVELOPMENT_PRINCIPAL = "local-development"
LOGGER = logging.getLogger(__name__)


class AgUiBoundaryError(ValueError):
    """One stable, user-safe rejection at the AG-UI protocol boundary."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class AgUiSecurityMiddleware:
    """Validate HTTP framing and buffer at most one bounded AG-UI request."""

    def __init__(self, application: Callable[..., Awaitable[None]]) -> None:
        self._application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["path"] != "/ag-ui"
            or scope["method"] != "POST"
        ):
            await self._application(scope, receive, send)
            return

        correlation_id = str(uuid4())
        scope.setdefault("state", {})["agentdesk_correlation_id"] = correlation_id
        headers = _headers(scope)
        content_type = headers.get("content-type", "").partition(";")[0].strip().casefold()
        if content_type != "application/json":
            await _reject(
                scope,
                receive,
                send,
                AgUiBoundaryError(
                    "unsupported_media_type",
                    "AG-UI requests require application/json.",
                    status_code=415,
                ),
                correlation_id,
            )
            return

        accept = headers.get("accept", "*/*").casefold()
        if "text/event-stream" not in accept and "*/*" not in accept:
            await _reject(
                scope,
                receive,
                send,
                AgUiBoundaryError(
                    "unsupported_response_type",
                    "AG-UI requests must accept text/event-stream.",
                    status_code=406,
                ),
                correlation_id,
            )
            return

        try:
            declared_length = _content_length(headers)
            if declared_length is not None and declared_length > MAX_AG_UI_REQUEST_BYTES:
                raise AgUiBoundaryError(
                    "request_too_large",
                    "The AG-UI request exceeds the allowed size.",
                    status_code=413,
                )
            body = await _bounded_body(receive)
        except AgUiBoundaryError as error:
            await _reject(scope, receive, send, error, correlation_id)
            return

        sent = False

        async def replay_body() -> Message:
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def add_correlation_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", ()))
                correlation_header = CORRELATION_HEADER.encode("ascii")
                if not any(
                    name.lower() == correlation_header for name, _ in response_headers
                ):
                    response_headers.append(
                        (correlation_header, correlation_id.encode("ascii"))
                    )
                message["headers"] = response_headers
            await send(message)

        await self._application(scope, replay_body, add_correlation_header)


def validate_run_input(input_data: RunAgentInput) -> None:
    """Apply application-specific bounds after official SDK model validation."""
    for identifier in (input_data.thread_id, input_data.run_id):
        if len(identifier) > MAX_AG_UI_IDENTIFIER_LENGTH:
            raise AgUiBoundaryError(
                "identifier_too_large",
                "An AG-UI correlation identifier exceeds the allowed size.",
            )

    if len(input_data.messages) > MAX_AG_UI_MESSAGES:
        raise AgUiBoundaryError(
            "message_limit_exceeded",
            "The AG-UI transcript contains too many messages.",
            status_code=413,
        )
    transcript_size = 0
    for message in input_data.messages:
        content = message.content
        if not isinstance(content, str):
            raise AgUiBoundaryError(
                "unsupported_message_content",
                "AgentDesk accepts text messages only.",
            )
        content_size = len(content.encode("utf-8"))
        if content_size > MAX_AG_UI_MESSAGE_BYTES:
            raise AgUiBoundaryError(
                "message_too_large",
                "An AG-UI message exceeds the allowed size.",
                status_code=413,
            )
        transcript_size += content_size
    if transcript_size > MAX_AG_UI_TRANSCRIPT_BYTES:
        raise AgUiBoundaryError(
            "transcript_too_large",
            "The AG-UI transcript exceeds the allowed size.",
            status_code=413,
        )

    if input_data.tools or input_data.context:
        raise AgUiBoundaryError(
            "unsupported_client_context",
            "AgentDesk does not accept browser-supplied tools or model context.",
        )
    forwarded_props = input_data.forwarded_props
    if not isinstance(forwarded_props, dict) or set(forwarded_props) != {"agentdesk"}:
        raise AgUiBoundaryError(
            "invalid_forwarded_props",
            "Only forwardedProps.agentdesk is accepted.",
        )
    _require_json_size(
        forwarded_props,
        maximum=MAX_AG_UI_FORWARDED_PROPS_BYTES,
        code="forwarded_props_too_large",
        message="The AG-UI forwarded properties exceed the allowed size.",
    )
    _require_json_size(
        input_data.state,
        maximum=MAX_AG_UI_STATE_BYTES,
        code="state_too_large",
        message="The AG-UI state exceeds the allowed size.",
    )


def request_principal_id(request: Request) -> str:
    """Read identity established by auth middleware, or the explicit local principal."""
    value = getattr(
        request.state,
        "agentdesk_principal_id",
        LOCAL_DEVELOPMENT_PRINCIPAL,
    )
    if not isinstance(value, str) or not value.strip():
        raise AgUiBoundaryError(
            "invalid_principal",
            "The authenticated principal is invalid.",
            status_code=401,
        )
    principal_id = value.strip()
    if len(principal_id) > MAX_AG_UI_IDENTIFIER_LENGTH:
        raise AgUiBoundaryError(
            "invalid_principal",
            "The authenticated principal is invalid.",
            status_code=401,
        )
    return principal_id


def require_state_size(value: Any) -> None:
    """Reject an outbound snapshot before it can become an oversized SSE event."""
    _require_json_size(
        value,
        maximum=MAX_AG_UI_STATE_BYTES,
        code="state_too_large",
        message="The AG-UI state exceeds the allowed size.",
    )


def require_patch_size(value: Any) -> None:
    """Reject an outbound state delta before it can become an oversized SSE event."""
    _require_json_size(
        value,
        maximum=MAX_AG_UI_PATCH_BYTES,
        code="patch_too_large",
        message="The AG-UI state patch exceeds the allowed size.",
    )


def _require_json_size(value: Any, *, maximum: int, code: str, message: str) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as error:
        raise AgUiBoundaryError("invalid_json_value", "AG-UI data must be JSON-safe.") from error
    if len(encoded) > maximum:
        raise AgUiBoundaryError(code, message, status_code=413)


async def _bounded_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    total = 0
    more_body = True
    while more_body:
        message = await receive()
        if message["type"] == "http.disconnect":
            return b""
        body = message.get("body", b"")
        total += len(body)
        if total > MAX_AG_UI_REQUEST_BYTES:
            raise AgUiBoundaryError(
                "request_too_large",
                "The AG-UI request exceeds the allowed size.",
                status_code=413,
            )
        chunks.append(body)
        more_body = message.get("more_body", False)
    return b"".join(chunks)


def _headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").casefold(): value.decode("latin-1")
        for key, value in scope.get("headers", ())
    }


def _content_length(headers: dict[str, str]) -> int | None:
    value = headers.get("content-length")
    if value is None:
        return None
    try:
        length = int(value)
    except ValueError as error:
        raise AgUiBoundaryError(
            "invalid_content_length",
            "The request Content-Length is invalid.",
        ) from error
    if length < 0:
        raise AgUiBoundaryError(
            "invalid_content_length",
            "The request Content-Length is invalid.",
        )
    return length


async def _reject(
    scope: Scope,
    receive: Receive,
    send: Send,
    error: AgUiBoundaryError,
    correlation_id: str,
) -> None:
    log_event(
        LOGGER,
        "agui.protocol_rejected",
        level=logging.WARNING,
        ids=CorrelationIds(correlation_id=correlation_id, agent="coordinator"),
        outcome="failed",
        error_code=error.code,
    )
    response = JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": str(error),
                "correlationId": correlation_id,
            }
        },
        headers={CORRELATION_HEADER: correlation_id},
    )
    await response(scope, receive, send)
