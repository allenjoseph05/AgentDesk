"""Typed LLM provider abstraction and adapter tests."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from packages.contracts import ResearchRequest
from packages.llm import (
    FakeLLMProvider,
    LLMProvider,
    LLMRefusalError,
    LLMResponseError,
    Message,
    MissingFixtureError,
    OpenAIResponsesProvider,
)


def test_fake_provider_returns_fresh_typed_fixture_without_network() -> None:
    provider = FakeLLMProvider({ResearchRequest: {"question": "Compare PostgreSQL and MongoDB."}})

    first = asyncio.run(
        provider.generate_structured(
            system_prompt="Return a validated research request.",
            messages=[Message(role="user", content="Compare the databases.")],
            response_model=ResearchRequest,
        )
    )
    second = asyncio.run(
        provider.generate_structured(
            system_prompt="Return a validated research request.",
            messages=[Message(role="user", content="Compare the databases.")],
            response_model=ResearchRequest,
        )
    )

    first.options.append("PostgreSQL")
    assert isinstance(provider, LLMProvider)
    assert second.options == []
    assert provider.calls[0].response_model is ResearchRequest


def test_fake_provider_validates_fixture_and_reports_missing_type() -> None:
    invalid = FakeLLMProvider({ResearchRequest: {"question": " "}})
    with pytest.raises(ValidationError):
        asyncio.run(
            invalid.generate_structured(
                system_prompt="Validate.",
                messages=[],
                response_model=ResearchRequest,
            )
        )

    missing = FakeLLMProvider({})
    with pytest.raises(MissingFixtureError):
        asyncio.run(
            missing.generate_structured(
                system_prompt="Validate.",
                messages=[],
                response_model=ResearchRequest,
            )
        )


def test_openai_adapter_uses_responses_strict_json_schema_without_network() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "question": "Compare PostgreSQL and MongoDB.",
                                        "options": [],
                                        "constraints": [],
                                        "criteria": [],
                                        "desired_depth": "normal",
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    async def invoke() -> ResearchRequest:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesProvider(
                api_key="test-key",
                model="test-structured-model",
                base_url="https://openai.invalid/v1",
                http_client=client,
            )
            return await provider.generate_structured(
                system_prompt="Return the requested structure.",
                messages=[Message(role="user", content="Compare databases.")],
                response_model=ResearchRequest,
            )

    result = asyncio.run(invoke())
    payload = captured["payload"]

    assert result.question == "Compare PostgreSQL and MongoDB."
    assert captured["authorization"] == "Bearer test-key"
    assert isinstance(payload, dict)
    assert payload["model"] == "test-structured-model"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    schema = payload["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.parametrize(
    "response_body, expected_error",
    [
        (
            {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}],
            },
            LLMRefusalError,
        ),
        (
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"question":""}'}],
                    }
                ],
            },
            LLMResponseError,
        ),
        ({"status": "incomplete", "output": []}, LLMResponseError),
    ],
)
def test_openai_adapter_surfaces_refusal_invalid_output_and_incomplete_response(
    response_body: dict,
    expected_error: type[Exception],
) -> None:
    async def invoke() -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json=response_body))
        async with httpx.AsyncClient(transport=transport) as client:
            provider = OpenAIResponsesProvider(
                api_key="test-key",
                model="test-model",
                http_client=client,
            )
            await provider.generate_structured(
                system_prompt="Return structured output.",
                messages=[],
                response_model=ResearchRequest,
            )

    with pytest.raises(expected_error):
        asyncio.run(invoke())


def test_agents_do_not_import_vendor_llm_sdks() -> None:
    from pathlib import Path

    agent_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("agents").rglob("*.py")
    )

    assert "import openai" not in agent_sources.casefold()
    assert "from openai" not in agent_sources.casefold()
    assert "import anthropic" not in agent_sources.casefold()
