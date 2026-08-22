"""Discovery, diagnostics, and skill-index tests for the Coordinator registry."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from google.protobuf.json_format import MessageToDict
from pydantic import ValidationError

from agents.coordinator.main import create_app
from agents.coordinator.registry import (
    AGENT_ENDPOINTS_ENV,
    REGISTRY_MAX_ATTEMPTS_ENV,
    REGISTRY_RETRY_DELAY_ENV,
    REGISTRY_TIMEOUT_ENV,
    AgentEndpointConfig,
    AgentRegistry,
    AgentRegistrySettings,
)
from agents.researcher.agent_card import create_agent_card as create_research_card


def _card_json(base_url: str) -> dict[str, object]:
    return MessageToDict(create_research_card(base_url))


def _settings(*endpoints: tuple[str, str]) -> AgentRegistrySettings:
    return AgentRegistrySettings(
        endpoints=[
            AgentEndpointConfig(agent_id=agent_id, base_url=base_url)
            for agent_id, base_url in endpoints
        ],
        request_timeout_seconds=1,
    )


def _registry(
    settings: AgentRegistrySettings,
    responses: dict[str, httpx.Response],
) -> AgentRegistry:
    def handler(request: httpx.Request) -> httpx.Response:
        try:
            return responses[str(request.url)]
        except KeyError as error:
            raise AssertionError(f"Unexpected registry request: {request.url}") from error

    return AgentRegistry(
        settings,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_environment_configuration_controls_agent_base_urls_and_timeout() -> None:
    settings = AgentRegistrySettings.from_environment(
        {
            AGENT_ENDPOINTS_ENV: json.dumps(
                {
                    "primary-research": "https://research.example/a2a",
                    "secondary-research": "https://backup.example",
                    "analyst": "https://analyst.example",
                }
            ),
            REGISTRY_TIMEOUT_ENV: "2.5",
            REGISTRY_MAX_ATTEMPTS_ENV: "4",
            REGISTRY_RETRY_DELAY_ENV: "0.25",
        }
    )

    assert [endpoint.agent_id for endpoint in settings.endpoints] == [
        "primary-research",
        "secondary-research",
        "analyst",
    ]
    assert [endpoint.normalized_url for endpoint in settings.endpoints] == [
        "https://research.example/a2a",
        "https://backup.example",
        "https://analyst.example",
    ]
    assert settings.request_timeout_seconds == 2.5
    assert settings.max_attempts == 4
    assert settings.retry_delay_seconds == 0.25


def test_default_configuration_includes_the_verifier_service() -> None:
    settings = AgentRegistrySettings.from_environment({})

    assert [endpoint.agent_id for endpoint in settings.endpoints] == [
        "researcher",
        "analyst",
        "verifier",
    ]
    assert settings.endpoints[-1].normalized_url == "http://127.0.0.1:8007"


@pytest.mark.parametrize(
    "environment",
    [
        {AGENT_ENDPOINTS_ENV: "not-json"},
        {AGENT_ENDPOINTS_ENV: "[]"},
        {AGENT_ENDPOINTS_ENV: "{}"},
    ],
)
def test_invalid_environment_configuration_is_rejected(environment: dict[str, str]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        AgentRegistrySettings.from_environment(environment)


def test_duplicate_configured_ids_and_urls_are_rejected() -> None:
    with pytest.raises(ValidationError, match="agent IDs"):
        _settings(
            ("research", "https://research-a.example"),
            ("research", "https://research-b.example"),
        )
    with pytest.raises(ValidationError, match="base URLs"):
        _settings(
            ("research-a", "https://research.example"),
            ("research-b", "https://research.example/"),
        )


def test_refresh_indexes_duplicate_skill_providers_in_configuration_order() -> None:
    first_url = "https://research-a.example"
    second_url = "https://research-b.example"
    settings = _settings(("research-a", first_url), ("research-b", second_url))
    registry = _registry(
        settings,
        {
            f"{first_url}/.well-known/agent-card.json": httpx.Response(
                200, json=_card_json(first_url)
            ),
            f"{second_url}/.well-known/agent-card.json": httpx.Response(
                200, json=_card_json(second_url)
            ),
        },
    )

    diagnostics = asyncio.run(registry.refresh())

    assert diagnostics == ()
    providers = registry.lookup_by_skill("web-research")
    assert [provider.agent_id for provider in providers] == ["research-a", "research-b"]
    assert registry.first_by_skill("web-research") is providers[0]
    assert registry.lookup_by_skill("not-advertised") == ()


def test_invalid_and_unreachable_cards_are_rejected_with_diagnostics() -> None:
    good_url = "https://good.example"
    broken_url = "https://broken.example"
    unavailable_url = "https://unavailable.example"
    wrong_origin_url = "https://wrong-origin.example"
    settings = _settings(
        ("good", good_url),
        ("broken", broken_url),
        ("unavailable", unavailable_url),
        ("wrong-origin", wrong_origin_url),
    )
    registry = _registry(
        settings,
        {
            f"{good_url}/.well-known/agent-card.json": httpx.Response(
                200, json=_card_json(good_url)
            ),
            f"{broken_url}/.well-known/agent-card.json": httpx.Response(
                200, json={"name": "Incomplete Agent"}
            ),
            f"{unavailable_url}/.well-known/agent-card.json": httpx.Response(503),
            f"{wrong_origin_url}/.well-known/agent-card.json": httpx.Response(
                200, json=_card_json("https://redirected.example")
            ),
        },
    )

    diagnostics = asyncio.run(registry.refresh())

    assert [agent.agent_id for agent in registry.agents] == ["good"]
    assert registry.get("broken") is None
    assert [(item.agent_id, item.code) for item in diagnostics] == [
        ("broken", "invalid_card"),
        ("unavailable", "fetch_failed"),
        ("wrong-origin", "invalid_card"),
    ]


def test_discovery_retries_transient_get_failures_but_not_permanent_responses() -> None:
    transient_url = "https://transient.example"
    transient_attempts = 0

    def transient_handler(request: httpx.Request) -> httpx.Response:
        nonlocal transient_attempts
        transient_attempts += 1
        if transient_attempts == 1:
            raise httpx.ConnectError("temporarily unavailable", request=request)
        return httpx.Response(200, json=_card_json(transient_url))

    transient_registry = AgentRegistry(
        AgentRegistrySettings(
            endpoints=[AgentEndpointConfig(agent_id="research", base_url=transient_url)],
            request_timeout_seconds=1,
            max_attempts=3,
            retry_delay_seconds=0,
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transient_handler)),
    )

    assert asyncio.run(transient_registry.refresh()) == ()
    assert transient_attempts == 2

    permanent_attempts = 0

    def permanent_handler(_: httpx.Request) -> httpx.Response:
        nonlocal permanent_attempts
        permanent_attempts += 1
        return httpx.Response(404)

    permanent_registry = AgentRegistry(
        AgentRegistrySettings(
            endpoints=[
                AgentEndpointConfig(
                    agent_id="missing",
                    base_url="https://missing.example",
                )
            ],
            request_timeout_seconds=1,
            max_attempts=3,
            retry_delay_seconds=0,
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(permanent_handler)),
    )

    diagnostics = asyncio.run(permanent_registry.refresh())
    assert [(item.agent_id, item.code) for item in diagnostics] == [
        ("missing", "fetch_failed")
    ]
    assert permanent_attempts == 1


def test_controlled_refresh_atomically_replaces_the_skill_snapshot() -> None:
    base_url = "https://research.example"
    card_response = _card_json(base_url)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=card_response)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    registry = AgentRegistry(_settings(("research", base_url)), http_client=client)

    asyncio.run(registry.refresh())
    assert registry.first_by_skill("web-research") is not None

    card_response = {"name": "Now invalid"}
    asyncio.run(registry.refresh())

    assert registry.agents == ()
    assert registry.lookup_by_skill("web-research") == ()
    assert registry.diagnostics[0].code == "invalid_card"


def test_coordinator_startup_refreshes_registry_and_reports_readiness() -> None:
    base_url = "https://research.example"
    registry = _registry(
        _settings(("research", base_url)),
        {
            f"{base_url}/.well-known/agent-card.json": httpx.Response(
                200, json=_card_json(base_url)
            )
        },
    )
    app = create_app(registry=registry)

    async def run_lifespan_and_request() -> dict[str, str | int]:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/ready")
            assert response.status_code == 200
            return response.json()

    readiness = asyncio.run(run_lifespan_and_request())

    assert readiness == {
        "service": "coordinator",
        "status": "ready",
        "registered_agents": 1,
        "diagnostics": 0,
    }
    assert registry.first_by_skill("source-synthesis") is not None
