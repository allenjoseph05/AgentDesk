"""Vendor-neutral typed LLM provider contract."""

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from packages.contracts.base import ContractModel, NonEmptyText


class Message(ContractModel):
    """One conversational input passed to a provider."""

    role: Literal["user", "assistant"]
    content: NonEmptyText


class LLMProviderError(RuntimeError):
    """Base exception for provider failures safe to expose to application code."""


class LLMRefusalError(LLMProviderError):
    """Raised when a model explicitly refuses the structured-output request."""


class LLMResponseError(LLMProviderError):
    """Raised when a provider response cannot validate as the requested model."""


@runtime_checkable
class LLMProvider(Protocol):
    """Interface consumed by agents for machine-validated model output."""

    async def generate_structured[ResponseT: BaseModel](
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        response_model: type[ResponseT],
    ) -> ResponseT: ...
