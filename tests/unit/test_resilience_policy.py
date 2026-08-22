"""Explicit timeout and bounded safe-retry policy tests."""

from __future__ import annotations

import asyncio

import pytest

from packages.resilience import OperationPolicy, OperationTimeoutError, run_with_policy


def test_retry_budget_requires_an_explicitly_idempotent_operation() -> None:
    with pytest.raises(ValueError, match="idempotent"):
        OperationPolicy(timeout_seconds=1, max_attempts=2)


def test_idempotent_operation_retries_only_to_its_bounded_attempt_budget() -> None:
    attempts = 0
    delays: list[float] = []

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("transient")
        return "completed"

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    result = asyncio.run(
        run_with_policy(
            "registry.discovery",
            operation,
            policy=OperationPolicy(
                timeout_seconds=1,
                max_attempts=3,
                idempotent=True,
                retry_delay_seconds=0.1,
                max_retry_delay_seconds=1,
            ),
            should_retry=lambda error: isinstance(error, ConnectionError),
            sleep=record_delay,
        )
    )

    assert result == "completed"
    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_non_retryable_failure_and_cancellation_are_never_replayed() -> None:
    failure_attempts = 0

    async def fail() -> None:
        nonlocal failure_attempts
        failure_attempts += 1
        raise ValueError("invalid response")

    with pytest.raises(ValueError, match="invalid response"):
        asyncio.run(
            run_with_policy(
                "registry.discovery",
                fail,
                policy=OperationPolicy(
                    timeout_seconds=1,
                    max_attempts=3,
                    idempotent=True,
                    retry_delay_seconds=0,
                ),
            )
        )
    assert failure_attempts == 1

    cancellation_attempts = 0

    async def cancel() -> None:
        nonlocal cancellation_attempts
        cancellation_attempts += 1
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_with_policy(
                "registry.discovery",
                cancel,
                policy=OperationPolicy(
                    timeout_seconds=1,
                    max_attempts=3,
                    idempotent=True,
                    retry_delay_seconds=0,
                ),
            )
        )
    assert cancellation_attempts == 1


def test_each_attempt_has_an_explicit_timeout_and_timeout_retries_are_bounded() -> None:
    attempts = 0

    async def hang() -> None:
        nonlocal attempts
        attempts += 1
        await asyncio.Future()

    with pytest.raises(OperationTimeoutError) as error:
        asyncio.run(
            run_with_policy(
                "research.fetch",
                hang,
                policy=OperationPolicy(
                    timeout_seconds=0.001,
                    max_attempts=2,
                    idempotent=True,
                    retry_delay_seconds=0,
                ),
            )
        )

    assert attempts == 2
    assert error.value.operation == "research.fetch"
    assert error.value.attempt == 2
