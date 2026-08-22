"""Explicit timeout and bounded retry policies for external operations."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

_OPERATION_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")


class OperationTimeoutError(TimeoutError):
    """One named operation exhausted its per-attempt deadline."""

    def __init__(self, operation: str, *, attempt: int, timeout_seconds: float) -> None:
        self.operation = operation
        self.attempt = attempt
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Operation {operation} timed out on attempt {attempt} "
            f"after {timeout_seconds:g} seconds."
        )


@dataclass(frozen=True)
class OperationPolicy:
    """A deadline and retry budget with an explicit idempotency declaration."""

    timeout_seconds: float
    max_attempts: int = 1
    idempotent: bool = False
    retry_delay_seconds: float = 0.1
    backoff_multiplier: float = 2.0
    max_retry_delay_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("Operation timeout must be positive.")
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("Operation max_attempts must be between 1 and 5.")
        if self.max_attempts > 1 and not self.idempotent:
            raise ValueError("Retries require an explicitly idempotent operation.")
        if self.retry_delay_seconds < 0 or self.max_retry_delay_seconds < 0:
            raise ValueError("Operation retry delays cannot be negative.")
        if self.backoff_multiplier < 1:
            raise ValueError("Operation backoff multiplier must be at least 1.")


async def run_with_policy[ResultT](
    operation_name: str,
    operation: Callable[[], Awaitable[ResultT]],
    *,
    policy: OperationPolicy,
    should_retry: Callable[[Exception], bool] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ResultT:
    """Run one operation with its deadline and optional safe retry budget."""
    if not _OPERATION_PATTERN.fullmatch(operation_name):
        raise ValueError("Operation names must be stable dotted identifiers.")

    retry_predicate = should_retry or (lambda _: False)
    final_error: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            async with asyncio.timeout(policy.timeout_seconds):
                return await operation()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            final_error = OperationTimeoutError(
                operation_name,
                attempt=attempt,
                timeout_seconds=policy.timeout_seconds,
            )
        except Exception as error:
            if not retry_predicate(error):
                raise
            final_error = error

        if attempt < policy.max_attempts:
            await sleep(_retry_delay(policy, attempt))

    if final_error is None:  # pragma: no cover - loop always returns or records a failure
        raise RuntimeError("Operation policy ended without a result or failure.")
    raise final_error


def _retry_delay(policy: OperationPolicy, completed_attempt: int) -> float:
    delay = policy.retry_delay_seconds * (
        policy.backoff_multiplier ** (completed_attempt - 1)
    )
    return min(delay, policy.max_retry_delay_seconds)
