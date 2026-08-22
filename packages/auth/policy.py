"""Environment-backed bearer authentication for browser and service boundaries."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from secrets import compare_digest
from typing import Literal
from uuid import uuid4

from pydantic import SecretStr, model_validator
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from packages.contracts.base import ContractModel, NonEmptyText
from packages.observability import CorrelationIds, log_event

AUTH_MODE_ENV = "AGENTDESK_AUTH_MODE"
BROWSER_TOKEN_ENV = "AGENTDESK_BROWSER_TOKEN"
SERVICE_TOKEN_ENV = "AGENTDESK_SERVICE_TOKEN"
BROWSER_PRINCIPAL_ENV = "AGENTDESK_BROWSER_PRINCIPAL_ID"
LOCAL_PRINCIPAL_ENV = "AGENTDESK_LOCAL_PRINCIPAL_ID"

AUTH_CORRELATION_HEADER = "x-agentdesk-correlation-id"
LOCAL_DEVELOPMENT_PRINCIPAL = "local-development"
MINIMUM_TOKEN_LENGTH = 16

AuthMode = Literal["local", "token"]
LOGGER = logging.getLogger(__name__)


class AuthenticationSettings(ContractModel):
    """Authentication mode and secrets loaded only from process configuration."""

    mode: AuthMode = "local"
    browser_token: SecretStr | None = None
    service_token: SecretStr | None = None
    browser_principal_id: NonEmptyText = "authenticated-browser"
    local_principal_id: NonEmptyText = LOCAL_DEVELOPMENT_PRINCIPAL

    @model_validator(mode="after")
    def validate_token_mode(self) -> AuthenticationSettings:
        if self.mode == "local":
            return self
        for label, token in (
            ("browser", self.browser_token),
            ("service", self.service_token),
        ):
            if token is None or len(token.get_secret_value()) < MINIMUM_TOKEN_LENGTH:
                raise ValueError(
                    f"Token authentication requires a {label} token of at least "
                    f"{MINIMUM_TOKEN_LENGTH} characters."
                )
        return self

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> AuthenticationSettings:
        source = environment if environment is not None else os.environ
        return cls.model_validate(
            {
                "mode": source.get(AUTH_MODE_ENV, "local"),
                "browser_token": source.get(BROWSER_TOKEN_ENV) or None,
                "service_token": source.get(SERVICE_TOKEN_ENV) or None,
                "browser_principal_id": source.get(
                    BROWSER_PRINCIPAL_ENV,
                    "authenticated-browser",
                ),
                "local_principal_id": source.get(
                    LOCAL_PRINCIPAL_ENV,
                    LOCAL_DEVELOPMENT_PRINCIPAL,
                ),
            }
        )

    def service_headers(self) -> dict[str, str]:
        """Return an immutable-call credential without exposing it in model output."""
        if self.mode != "token" or self.service_token is None:
            return {}
        return {"Authorization": f"Bearer {self.service_token.get_secret_value()}"}


class BrowserAuthenticationMiddleware:
    """Authenticate AG-UI and session-history calls and establish their principal."""

    def __init__(
        self,
        application: Callable[..., Awaitable[None]],
        *,
        settings: AuthenticationSettings,
    ) -> None:
        self._application = application
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_browser_path(scope["path"]):
            await self._application(scope, receive, send)
            return
        if self._settings.mode == "local":
            scope.setdefault("state", {})["agentdesk_principal_id"] = (
                self._settings.local_principal_id
            )
            await self._application(scope, receive, send)
            return
        if not _authorized(scope, self._settings.browser_token):
            await _reject(scope, receive, send, boundary="browser")
            return
        scope.setdefault("state", {})["agentdesk_principal_id"] = (
            self._settings.browser_principal_id
        )
        await self._application(scope, receive, send)


class ServiceAuthenticationMiddleware:
    """Protect specialist task routes while leaving operational discovery public."""

    def __init__(
        self,
        application: Callable[..., Awaitable[None]],
        *,
        settings: AuthenticationSettings,
    ) -> None:
        self._application = application
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or self._settings.mode == "local"
            or _is_public_service_path(scope["path"])
        ):
            await self._application(scope, receive, send)
            return
        if not _authorized(scope, self._settings.service_token):
            await _reject(scope, receive, send, boundary="service")
            return
        await self._application(scope, receive, send)


def _authorized(scope: Scope, expected: SecretStr | None) -> bool:
    if expected is None:
        return False
    authorization = next(
        (
            value.decode("latin-1")
            for name, value in scope.get("headers", ())
            if name.lower() == b"authorization"
        ),
        None,
    )
    if authorization is None or not authorization.startswith("Bearer "):
        return False
    supplied = authorization.removeprefix("Bearer ")
    return bool(supplied) and compare_digest(supplied, expected.get_secret_value())


async def _reject(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    boundary: Literal["browser", "service"],
) -> None:
    correlation_id = str(uuid4())
    log_event(
        LOGGER,
        "authentication.rejected",
        level=logging.WARNING,
        ids=CorrelationIds(correlation_id=correlation_id),
        outcome="failed",
        error_code="authentication_failed",
    )
    response = JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "authentication_failed",
                "message": "Authentication is required.",
                "correlationId": correlation_id,
                "boundary": boundary,
            }
        },
        headers={
            AUTH_CORRELATION_HEADER: correlation_id,
            "WWW-Authenticate": "Bearer",
            "Cache-Control": "no-store",
        },
    )
    await response(scope, receive, send)


def _is_browser_path(path: str) -> bool:
    return path == "/ag-ui" or path == "/api/sessions" or path.startswith("/api/sessions/")


def _is_public_service_path(path: str) -> bool:
    return path in {"/health", "/ready"} or path.startswith("/.well-known/")
