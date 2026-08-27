"""Hosted Coordinator startup-gating tests."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from scripts.start_hosted_coordinator import (
    dependency_readiness_urls,
    wait_for_dependencies,
)


class ReadyResponse:
    status = 200

    def __enter__(self) -> ReadyResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"status": "ready"}).encode()


def test_hosted_dependencies_use_platform_private_hostports() -> None:
    assert dependency_readiness_urls(
        {
            "RESEARCH_AGENT_HOSTPORT": "researcher:10000",
            "ANALYST_AGENT_HOSTPORT": "analyst:10000",
            "VERIFIER_AGENT_HOSTPORT": "verifier:10000",
        }
    ) == (
        "http://researcher:10000/ready",
        "http://analyst:10000/ready",
        "http://verifier:10000/ready",
    )


def test_hosted_startup_accepts_only_ready_json_responses() -> None:
    calls: list[tuple[str, float]] = []

    def open_ready(url: str, *, timeout: float) -> ReadyResponse:
        calls.append((url, timeout))
        return ReadyResponse()

    wait_for_dependencies(
        ["http://researcher:10000/ready"],
        timeout_seconds=30,
        open_url=open_ready,
    )

    assert calls == [("http://researcher:10000/ready", 5)]


def test_hosted_startup_fails_with_a_bounded_pending_service_list() -> None:
    times: Iterator[float] = iter((0, 2))

    def unavailable(*_: object, **__: object) -> ReadyResponse:
        raise OSError("not ready")

    with pytest.raises(TimeoutError, match="http://analyst:10000/ready"):
        wait_for_dependencies(
            ["http://analyst:10000/ready"],
            timeout_seconds=1,
            open_url=unavailable,
            monotonic=lambda: next(times),
            sleep=lambda _: None,
        )


def test_hosted_startup_requires_every_specialist_endpoint() -> None:
    with pytest.raises(ValueError, match="verifier endpoint"):
        dependency_readiness_urls(
            {
                "RESEARCH_AGENT_HOSTPORT": "researcher:10000",
                "ANALYST_AGENT_HOSTPORT": "analyst:10000",
            }
        )
