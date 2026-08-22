"""Browser and service authentication boundary tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from agents.analyst.main import create_app as create_analyst_app
from agents.coordinator.a2a_client import A2AClientAdapter, RemoteAuthenticationError
from agents.coordinator.main import create_app as create_coordinator_app
from agents.coordinator.registry import RegisteredAgent
from agents.coordinator.run_adapter import (
    CoordinatorCommand,
    CoordinatorRunOutcome,
    CoordinatorRunUpdate,
)
from agents.researcher.agent_card import create_agent_card as create_research_card
from agents.researcher.main import create_app as create_research_app
from agents.verifier.main import create_app as create_verifier_app
from packages.auth import AuthenticationSettings
from packages.contracts import EvidenceBundle, ResearchRequest

TOKEN = "test-token-at-least-16-characters"
OTHER_TOKEN = "different-token-at-least-16-characters"


def _token_settings() -> AuthenticationSettings:
    return AuthenticationSettings(
        mode="token",
        browser_token=TOKEN,
        service_token=TOKEN,
        browser_principal_id="user-authenticated",
    )


class RecordingExecutor:
    def __init__(self) -> None:
        self.commands: list[CoordinatorCommand] = []

    async def execute(
        self,
        command: CoordinatorCommand,
    ) -> AsyncIterator[CoordinatorRunUpdate]:
        self.commands.append(command)
        yield CoordinatorRunOutcome(status="completed")


def _run_payload() -> dict[str, Any]:
    question = "Should we use PostgreSQL or MongoDB?"
    return {
        "threadId": "thread-auth",
        "runId": "run-auth",
        "state": {},
        "messages": [
            {
                "id": "message-auth",
                "role": "user",
                "content": question,
            }
        ],
        "tools": [],
        "context": [],
        "forwardedProps": {
            "agentdesk": {
                "schemaVersion": "1.0",
                "actionId": "action-auth",
                "type": "start_research",
                "sessionId": None,
                "payload": {
                    "question": question,
                    "options": [],
                    "constraints": [],
                    "criteria": [],
                    "desiredDepth": "normal",
                },
            }
        },
    }


def test_token_mode_requires_environment_grade_secrets_and_redacts_them() -> None:
    with pytest.raises(ValidationError, match="at least 16"):
        AuthenticationSettings(
            mode="token",
            browser_token="short",
            service_token=TOKEN,
        )

    settings = AuthenticationSettings.from_environment(
        {
            "AGENTDESK_AUTH_MODE": "token",
            "AGENTDESK_BROWSER_TOKEN": TOKEN,
            "AGENTDESK_SERVICE_TOKEN": OTHER_TOKEN,
            "AGENTDESK_BROWSER_PRINCIPAL_ID": "user-42",
        }
    )

    assert settings.browser_principal_id == "user-42"
    assert settings.service_headers() == {"Authorization": f"Bearer {OTHER_TOKEN}"}
    assert TOKEN not in repr(settings)
    assert OTHER_TOKEN not in repr(settings)


def test_browser_boundary_authenticates_before_delegation_and_binds_principal() -> None:
    async def scenario() -> tuple[
        httpx.Response,
        httpx.Response,
        httpx.Response,
        RecordingExecutor,
    ]:
        executor = RecordingExecutor()
        application = create_coordinator_app(
            command_executor=executor,
            auth_settings=_token_settings(),
        )
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.post(
                "/ag-ui",
                json=_run_payload(),
                headers={"Accept": "text/event-stream"},
            )
            invalid = await client.post(
                "/ag-ui",
                json=_run_payload(),
                headers={
                    "Accept": "text/event-stream",
                    "Authorization": f"Bearer {OTHER_TOKEN}",
                },
            )
            accepted = await client.post(
                "/ag-ui",
                json=_run_payload(),
                headers={
                    "Accept": "text/event-stream",
                    "Authorization": f"Bearer {TOKEN}",
                },
            )
        return missing, invalid, accepted, executor

    missing, invalid, accepted, executor = asyncio.run(scenario())

    for rejected in (missing, invalid):
        assert rejected.status_code == 401
        assert rejected.json()["error"]["code"] == "authentication_failed"
        assert rejected.headers["www-authenticate"] == "Bearer"
    assert accepted.status_code == 200
    assert len(executor.commands) == 1
    assert executor.commands[0].correlation.principal_id == "user-authenticated"


@pytest.mark.parametrize(
    "application_factory",
    [create_research_app, create_analyst_app, create_verifier_app],
)
def test_specialist_task_routes_require_service_token_but_cards_remain_public(
    application_factory: Callable[..., FastAPI],
) -> None:
    async def scenario() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        application = application_factory(auth_settings=_token_settings())
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            card = await client.get("/.well-known/agent-card.json")
            rejected = await client.post("/message:send", json={})
            authenticated = await client.post(
                "/message:send",
                json={},
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
        return card, rejected, authenticated

    card, rejected, authenticated = asyncio.run(scenario())

    assert card.status_code == 200
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "authentication_failed"
    assert authenticated.status_code != 401


def test_coordinator_sends_service_token_and_auth_failure_is_not_retried() -> None:
    calls = 0
    observed_authorization: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls, observed_authorization
        calls += 1
        observed_authorization = request.headers.get("Authorization")
        return httpx.Response(401, json={"error": {"code": "authentication_failed"}})

    agent = RegisteredAgent(
        agent_id="researcher",
        base_url="https://research.example",
        card=create_research_card("https://research.example"),
    )
    adapter = A2AClientAdapter(
        _token_settings(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RemoteAuthenticationError) as error:
        asyncio.run(
            adapter.execute(
                agent=agent,
                request=ResearchRequest(question="What is known?"),
                artifact_name="final_evidence_bundle",
                payload_model=EvidenceBundle,
                timeout_seconds=1,
            )
        )

    assert error.value.code == "authentication_failed"
    assert observed_authorization == f"Bearer {TOKEN}"
    assert calls == 1
