"""Deterministic typed LLM provider for tests and fixture-driven demos."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from packages.llm.provider import Message


class MissingFixtureError(LookupError):
    """Raised when a fake provider has no fixture for the requested model."""


@dataclass(frozen=True)
class RecordedCall:
    """Inspectable prompt metadata captured without hidden model reasoning."""

    system_prompt: str
    messages: tuple[Message, ...]
    response_model: type[BaseModel]


class FakeLLMProvider:
    """Return fresh validated copies of configured typed fixtures."""

    def __init__(self, fixtures: Mapping[type[BaseModel], BaseModel | Mapping[str, Any]]) -> None:
        self._fixtures = dict(fixtures)
        self.calls: list[RecordedCall] = []

    async def generate_structured[ResponseT: BaseModel](
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        response_model: type[ResponseT],
    ) -> ResponseT:
        self.calls.append(
            RecordedCall(
                system_prompt=system_prompt,
                messages=tuple(messages),
                response_model=response_model,
            )
        )
        try:
            fixture = self._fixtures[response_model]
        except KeyError as error:
            raise MissingFixtureError(
                f"No deterministic fixture registered for {response_model.__name__}."
            ) from error

        raw_fixture = (
            fixture.model_dump(mode="python") if isinstance(fixture, BaseModel) else fixture
        )
        return response_model.model_validate(raw_fixture).model_copy(deep=True)
