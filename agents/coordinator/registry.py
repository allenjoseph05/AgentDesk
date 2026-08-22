"""Configuration-driven discovery registry for remote A2A specialists."""

from __future__ import annotations

import asyncio
import json
import os
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.errors import AgentCardResolutionError
from a2a.types import AgentCard
from a2a.utils.constants import TransportProtocol
from a2a.utils.errors import InvalidParamsError
from a2a.utils.proto_utils import validate_proto_required_fields
from pydantic import AnyHttpUrl, Field, FiniteFloat, model_validator

from packages.contracts.base import ContractModel, NonEmptyText
from packages.resilience import OperationPolicy, OperationTimeoutError, run_with_policy

DEFAULT_RESEARCH_AGENT_URL = "http://127.0.0.1:8005"
DEFAULT_ANALYST_AGENT_URL = "http://127.0.0.1:8006"
DEFAULT_VERIFIER_AGENT_URL = "http://127.0.0.1:8007"
AGENT_ENDPOINTS_ENV = "AGENTDESK_AGENT_ENDPOINTS"
REGISTRY_TIMEOUT_ENV = "AGENTDESK_REGISTRY_TIMEOUT_SECONDS"
REGISTRY_MAX_ATTEMPTS_ENV = "AGENTDESK_REGISTRY_MAX_ATTEMPTS"
REGISTRY_RETRY_DELAY_ENV = "AGENTDESK_REGISTRY_RETRY_DELAY_SECONDS"

PositiveTimeout = Annotated[FiniteFloat, Field(gt=0, le=30)]
RetryDelay = Annotated[FiniteFloat, Field(ge=0, le=5)]
RetryAttempts = Annotated[int, Field(ge=1, le=5)]
DiagnosticCode = Literal["fetch_failed", "invalid_card"]


class AgentEndpointConfig(ContractModel):
    """One configured, trusted discovery endpoint."""

    agent_id: NonEmptyText
    base_url: AnyHttpUrl

    @model_validator(mode="after")
    def validate_base_url(self) -> AgentEndpointConfig:
        if any(
            value is not None
            for value in (
                self.base_url.username,
                self.base_url.password,
                self.base_url.query,
                self.base_url.fragment,
            )
        ):
            raise ValueError("Agent base URL cannot contain credentials, query, or fragment.")
        return self

    @property
    def normalized_url(self) -> str:
        return str(self.base_url).rstrip("/")


class AgentRegistrySettings(ContractModel):
    """Validated Coordinator discovery configuration."""

    endpoints: list[AgentEndpointConfig] = Field(min_length=1)
    request_timeout_seconds: PositiveTimeout = 5
    max_attempts: RetryAttempts = 3
    retry_delay_seconds: RetryDelay = 0.1

    @model_validator(mode="after")
    def validate_unique_endpoints(self) -> AgentRegistrySettings:
        agent_ids = [endpoint.agent_id for endpoint in self.endpoints]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("Configured agent IDs must be unique.")
        urls = [endpoint.normalized_url.casefold() for endpoint in self.endpoints]
        if len(urls) != len(set(urls)):
            raise ValueError("Configured agent base URLs must be unique.")
        return self

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> AgentRegistrySettings:
        """Load endpoint mappings from environment without accepting arbitrary fields."""
        source = os.environ if environ is None else environ
        raw_endpoints = source.get(AGENT_ENDPOINTS_ENV)
        if raw_endpoints:
            try:
                parsed = json.loads(raw_endpoints)
            except json.JSONDecodeError as error:
                raise ValueError(f"{AGENT_ENDPOINTS_ENV} must be valid JSON.") from error
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError(f"{AGENT_ENDPOINTS_ENV} must be a non-empty JSON object.")
            endpoints = [
                AgentEndpointConfig(agent_id=agent_id, base_url=base_url)
                for agent_id, base_url in parsed.items()
            ]
        else:
            endpoints = [
                AgentEndpointConfig.model_validate(
                    {
                        "agent_id": "researcher",
                        "base_url": source.get(
                            "RESEARCH_AGENT_URL", DEFAULT_RESEARCH_AGENT_URL
                        ),
                    }
                ),
                AgentEndpointConfig.model_validate(
                    {
                        "agent_id": "analyst",
                        "base_url": source.get(
                            "ANALYST_AGENT_URL", DEFAULT_ANALYST_AGENT_URL
                        ),
                    }
                ),
                AgentEndpointConfig.model_validate(
                    {
                        "agent_id": "verifier",
                        "base_url": source.get(
                            "VERIFIER_AGENT_URL", DEFAULT_VERIFIER_AGENT_URL
                        ),
                    }
                ),
            ]

        timeout = source.get(REGISTRY_TIMEOUT_ENV, "5")
        attempts = source.get(REGISTRY_MAX_ATTEMPTS_ENV, "3")
        retry_delay = source.get(REGISTRY_RETRY_DELAY_ENV, "0.1")
        return cls.model_validate(
            {
                "endpoints": endpoints,
                "request_timeout_seconds": timeout,
                "max_attempts": attempts,
                "retry_delay_seconds": retry_delay,
            }
        )


class RegistryDiagnostic(ContractModel):
    """Safe discovery failure attached to one configured endpoint."""

    agent_id: NonEmptyText
    base_url: AnyHttpUrl
    code: DiagnosticCode
    message: NonEmptyText


@dataclass(frozen=True)
class RegisteredAgent:
    """A successfully resolved Agent Card plus its configured identity."""

    agent_id: str
    base_url: str
    card: AgentCard


class AgentRegistry:
    """Resolve Agent Cards and index all healthy providers by advertised skill."""

    def __init__(
        self,
        settings: AgentRegistrySettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_http_client = http_client is None
        self._http_client = http_client
        self._agents: dict[str, RegisteredAgent] = {}
        self._providers_by_skill: dict[str, tuple[RegisteredAgent, ...]] = {}
        self._diagnostics: tuple[RegistryDiagnostic, ...] = ()

    @property
    def agents(self) -> tuple[RegisteredAgent, ...]:
        return tuple(self._agents.values())

    @property
    def diagnostics(self) -> tuple[RegistryDiagnostic, ...]:
        return self._diagnostics

    def get(self, agent_id: str) -> RegisteredAgent | None:
        return self._agents.get(agent_id)

    def lookup_by_skill(self, skill_id: str) -> tuple[RegisteredAgent, ...]:
        """Return every healthy provider in configured preference order."""
        return self._providers_by_skill.get(skill_id, ())

    def first_by_skill(self, skill_id: str) -> RegisteredAgent | None:
        providers = self.lookup_by_skill(skill_id)
        return providers[0] if providers else None

    async def refresh(self) -> tuple[RegistryDiagnostic, ...]:
        """Atomically replace the registry with the latest valid discovery results."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._settings.request_timeout_seconds,
                follow_redirects=False,
            )
        results = await asyncio.gather(
            *(self._resolve(endpoint) for endpoint in self._settings.endpoints)
        )
        agents: dict[str, RegisteredAgent] = {}
        diagnostics: list[RegistryDiagnostic] = []
        providers: dict[str, list[RegisteredAgent]] = {}
        for agent, diagnostic in results:
            if diagnostic is not None:
                diagnostics.append(diagnostic)
                continue
            if agent is None:  # pragma: no cover - result contract guarantees one branch
                continue
            agents[agent.agent_id] = agent
            for skill in agent.card.skills:
                providers.setdefault(skill.id, []).append(agent)

        self._agents = agents
        self._providers_by_skill = {
            skill_id: tuple(skill_providers)
            for skill_id, skill_providers in providers.items()
        }
        self._diagnostics = tuple(diagnostics)
        return self._diagnostics

    async def aclose(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _resolve(
        self,
        endpoint: AgentEndpointConfig,
    ) -> tuple[RegisteredAgent | None, RegistryDiagnostic | None]:
        if self._http_client is None:  # pragma: no cover - refresh initializes the client
            raise RuntimeError("Registry HTTP client is not initialized.")
        try:
            resolver = A2ACardResolver(self._http_client, endpoint.normalized_url)

            async def fetch_card() -> AgentCard:
                return await resolver.get_agent_card(
                    http_kwargs={"timeout": self._settings.request_timeout_seconds}
                )

            card = await run_with_policy(
                "registry.discovery",
                fetch_card,
                policy=OperationPolicy(
                    timeout_seconds=self._settings.request_timeout_seconds,
                    max_attempts=self._settings.max_attempts,
                    idempotent=True,
                    retry_delay_seconds=self._settings.retry_delay_seconds,
                ),
                should_retry=_retryable_resolution_error,
            )
        except OperationTimeoutError as error:
            return None, self._diagnostic(endpoint, "fetch_failed", str(error))
        except AgentCardResolutionError as error:
            return None, self._diagnostic(endpoint, "fetch_failed", str(error))
        except (AttributeError, TypeError, ValueError) as error:
            return None, self._diagnostic(
                endpoint,
                "invalid_card",
                f"Agent Card response was not a valid object: {error}",
            )

        try:
            _validate_card(endpoint, card)
        except (InvalidParamsError, ValueError) as error:
            return None, self._diagnostic(endpoint, "invalid_card", str(error))
        return (
            RegisteredAgent(
                agent_id=endpoint.agent_id,
                base_url=endpoint.normalized_url,
                card=card,
            ),
            None,
        )

    @staticmethod
    def _diagnostic(
        endpoint: AgentEndpointConfig,
        code: DiagnosticCode,
        message: str,
    ) -> RegistryDiagnostic:
        return RegistryDiagnostic(
            agent_id=endpoint.agent_id,
            base_url=endpoint.base_url,
            code=code,
            message=message,
        )


def _validate_card(endpoint: AgentEndpointConfig, card: AgentCard) -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"label\(\) is deprecated",
            category=DeprecationWarning,
        )
        validate_proto_required_fields(card)
    if not card.name.strip():
        raise ValueError("Agent Card name cannot be blank.")
    if not card.skills:
        raise ValueError("Agent Card must advertise at least one skill.")
    skill_ids = [skill.id for skill in card.skills]
    if len(skill_ids) != len(set(skill_ids)):
        raise ValueError("Agent Card skill IDs must be unique.")

    configured_origin = _origin(endpoint.normalized_url)
    compatible_interface = False
    for interface in card.supported_interfaces:
        if _origin(interface.url) != configured_origin:
            raise ValueError("Agent Card interface origin must match its configured base URL.")
        if interface.protocol_binding == TransportProtocol.HTTP_JSON:
            compatible_interface = True
    if not compatible_interface:
        raise ValueError("Agent Card must advertise an HTTP+JSON interface.")


def _retryable_resolution_error(error: Exception) -> bool:
    if not isinstance(error, AgentCardResolutionError):
        return False
    if error.status_code is not None:
        return error.status_code in {408, 425, 429} or error.status_code >= 500
    return isinstance(error.__cause__, httpx.RequestError)


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.casefold()
    default_port = 80 if scheme == "http" else 443 if scheme == "https" else None
    return scheme, (parsed.hostname or "").casefold(), parsed.port or default_port
