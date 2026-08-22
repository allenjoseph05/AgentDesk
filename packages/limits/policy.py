"""Environment-backed limits for workflow fan-out and provider requests."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Literal, cast

from pydantic import Field

from packages.contracts.base import ContractModel
from packages.contracts.domain import Depth

MAX_REMOTE_TASKS_ENV = "AGENTDESK_MAX_REMOTE_TASKS_PER_SESSION"
MAX_RESEARCH_DEPTH_ENV = "AGENTDESK_MAX_RESEARCH_DEPTH"
LLM_REQUEST_BUDGET_ENV = "AGENTDESK_LLM_REQUEST_BUDGET"
TOOL_REQUEST_BUDGET_ENV = "AGENTDESK_TOOL_REQUEST_BUDGET"

LimitCode = Literal[
    "remote_task_limit_exceeded",
    "research_depth_limit_exceeded",
    "llm_request_budget_exceeded",
    "tool_request_budget_exceeded",
]

_DEPTH_RANK: dict[Depth, int] = {"fast": 0, "normal": 1, "deep": 2}
_LIMIT_CODES: set[str] = {
    "remote_task_limit_exceeded",
    "research_depth_limit_exceeded",
    "llm_request_budget_exceeded",
    "tool_request_budget_exceeded",
}
_STATUS_PREFIX = "AgentDesk limit exceeded ["
_REMOTE_SAFE_MESSAGES: dict[LimitCode, str] = {
    "remote_task_limit_exceeded": "The remote-task limit was reached.",
    "research_depth_limit_exceeded": (
        "The requested research depth exceeds the specialist's configured maximum."
    ),
    "llm_request_budget_exceeded": (
        "The configured LLM request budget was reached before this operation could complete."
    ),
    "tool_request_budget_exceeded": (
        "The configured tool request budget was reached before this operation could complete."
    ),
}


class LimitExceededError(RuntimeError):
    """A configured workflow or provider-request limit would be exceeded."""

    def __init__(self, code: LimitCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class LimitSettings(ContractModel):
    """Fail-fast limits shared by the Coordinator and specialist services."""

    max_remote_tasks_per_session: int = Field(default=20, ge=1, le=1000)
    max_research_depth: Depth = "deep"
    llm_request_budget: int = Field(default=3, ge=0, le=1000)
    tool_request_budget: int = Field(default=25, ge=0, le=10000)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> LimitSettings:
        source = environment if environment is not None else os.environ
        return cls.model_validate(
            {
                "max_remote_tasks_per_session": source.get(MAX_REMOTE_TASKS_ENV, "20"),
                "max_research_depth": source.get(MAX_RESEARCH_DEPTH_ENV, "deep"),
                "llm_request_budget": source.get(LLM_REQUEST_BUDGET_ENV, "3"),
                "tool_request_budget": source.get(TOOL_REQUEST_BUDGET_ENV, "25"),
            }
        )

    def require_research_depth(self, requested: Depth) -> None:
        if _DEPTH_RANK[requested] <= _DEPTH_RANK[self.max_research_depth]:
            return
        raise LimitExceededError(
            "research_depth_limit_exceeded",
            "The requested research depth exceeds this workspace's configured maximum "
            f"of {self.max_research_depth}.",
        )


class RequestBudget:
    """Count actual provider attempts for one service request."""

    def __init__(self, settings: LimitSettings) -> None:
        self._settings = settings
        self.llm_requests = 0
        self.tool_requests = 0

    def consume_llm(self) -> None:
        if self.llm_requests >= self._settings.llm_request_budget:
            raise LimitExceededError(
                "llm_request_budget_exceeded",
                "The configured LLM request budget was reached before this operation "
                "could complete.",
            )
        self.llm_requests += 1

    def consume_tool(self) -> None:
        if self.tool_requests >= self._settings.tool_request_budget:
            raise LimitExceededError(
                "tool_request_budget_exceeded",
                "The configured tool request budget was reached before this operation "
                "could complete.",
            )
        self.tool_requests += 1

    async def call_llm[ResultT](
        self,
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        self.consume_llm()
        return await operation()

    async def call_tool[ResultT](
        self,
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        self.consume_tool()
        return await operation()


def limit_status_message(error: LimitExceededError) -> str:
    """Encode a bounded limit failure across the text-only A2A status boundary."""
    return f"{_STATUS_PREFIX}{error.code}]: {error}"


def parse_limit_status_message(message: str) -> LimitExceededError | None:
    """Recover a trusted typed limit failure from a specialist status message."""
    if not message.startswith(_STATUS_PREFIX):
        return None
    encoded_code, separator, detail = message.removeprefix(_STATUS_PREFIX).partition("]: ")
    if not separator or encoded_code not in _LIMIT_CODES or not detail.strip():
        return None
    code = cast(LimitCode, encoded_code)
    return LimitExceededError(code, _REMOTE_SAFE_MESSAGES[code])
