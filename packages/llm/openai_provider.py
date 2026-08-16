"""OpenAI Responses API adapter for strict structured outputs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from packages.llm.provider import (
    LLMProviderError,
    LLMRefusalError,
    LLMResponseError,
    Message,
)

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIResponsesProvider:
    """Generate Pydantic payloads through OpenAI's strict JSON Schema format."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key must not be blank.")
        if not model.strip():
            raise ValueError("OpenAI model must not be blank.")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._http_client = http_client

    async def generate_structured[ResponseT: BaseModel](
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        response_model: type[ResponseT],
    ) -> ResponseT:
        payload = self._request_payload(system_prompt, messages, response_model)
        if self._http_client is not None:
            response = await self._post(self._http_client, payload)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await self._post(client, payload)
        return self._parse_response(response, response_model)

    async def _post(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
    ) -> httpx.Response:
        try:
            response = await client.post(
                f"{self._base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as error:
            raise LLMProviderError(
                f"OpenAI Responses API returned HTTP {error.response.status_code}."
            ) from error
        except httpx.HTTPError as error:
            raise LLMProviderError("OpenAI Responses API request failed.") from error

    def _request_payload[ResponseT: BaseModel](
        self,
        system_prompt: str,
        messages: list[Message],
        response_model: type[ResponseT],
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "instructions": system_prompt,
            "input": [message.model_dump(mode="json") for message in messages],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _schema_name(response_model),
                    "schema": _strict_json_schema(response_model.model_json_schema()),
                    "strict": True,
                }
            },
        }

    @staticmethod
    def _parse_response[ResponseT: BaseModel](
        response: httpx.Response,
        response_model: type[ResponseT],
    ) -> ResponseT:
        try:
            body = response.json()
        except ValueError as error:
            raise LLMResponseError("OpenAI response was not valid JSON.") from error

        if body.get("status") != "completed":
            raise LLMResponseError("OpenAI response did not complete successfully.")

        output_text = _extract_output_text(body)
        try:
            return response_model.model_validate_json(output_text)
        except (ValidationError, ValueError) as error:
            raise LLMResponseError(
                f"OpenAI output did not validate as {response_model.__name__}."
            ) from error


def _schema_name(response_model: type[BaseModel]) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]", "_", response_model.__name__)
    return normalized[:64] or "structured_response"


def _strict_json_schema(value: Any) -> Any:
    """Adapt Pydantic JSON Schema to OpenAI's strict structured-output subset."""
    if isinstance(value, list):
        return [_strict_json_schema(item) for item in value]
    if not isinstance(value, Mapping):
        return value

    result = {
        key: _strict_json_schema(item)
        for key, item in value.items()
        if key not in {"default", "format"}
    }
    properties = result.get("properties")
    if isinstance(properties, Mapping):
        result["required"] = list(properties)
        result["additionalProperties"] = False
    return result


def _extract_output_text(body: Mapping[str, Any]) -> str:
    for output in body.get("output", []):
        if not isinstance(output, Mapping) or output.get("type") != "message":
            continue
        for content in output.get("content", []):
            if not isinstance(content, Mapping):
                continue
            if content.get("type") == "refusal":
                raise LLMRefusalError("OpenAI refused the structured-output request.")
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise LLMResponseError("OpenAI response did not contain structured output text.")
