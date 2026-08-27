"""Wait for hosted specialists, then start the deterministic Coordinator."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

import uvicorn

from packages.config import load_project_environment, service_url_from_environment

DEPENDENCIES = (
    ("RESEARCH_AGENT_URL", "RESEARCH_AGENT_HOSTPORT", "researcher"),
    ("ANALYST_AGENT_URL", "ANALYST_AGENT_HOSTPORT", "analyst"),
    ("VERIFIER_AGENT_URL", "VERIFIER_AGENT_HOSTPORT", "verifier"),
)


class HttpResponse(Protocol):
    status: int

    def __enter__(self) -> HttpResponse: ...

    def __exit__(self, *args: object) -> None: ...

    def read(self) -> bytes: ...


def dependency_readiness_urls(environ: Mapping[str, str]) -> tuple[str, ...]:
    """Build private readiness URLs from full URLs or Render host/port properties."""
    urls: list[str] = []
    for url_name, hostport_name, label in DEPENDENCIES:
        url = service_url_from_environment(
            url_name,
            hostport_name,
            "",
            environ=environ,
        )
        if not url:
            raise ValueError(f"Hosted Coordinator is missing the {label} endpoint.")
        urls.append(f"{url.rstrip('/')}/ready")
    return tuple(urls)


def wait_for_dependencies(
    urls: Sequence[str],
    *,
    timeout_seconds: float,
    interval_seconds: float = 2,
    open_url: Callable[..., HttpResponse] = urllib.request.urlopen,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait until every dependency reports ready, or fail within a fixed deadline."""
    if timeout_seconds <= 0 or timeout_seconds > 900:
        raise ValueError("Hosted startup timeout must be between 0 and 900 seconds.")
    if interval_seconds <= 0:
        raise ValueError("Hosted startup interval must be positive.")
    deadline = monotonic() + timeout_seconds
    pending = tuple(urls)
    while pending:
        still_pending: list[str] = []
        for url in pending:
            try:
                with open_url(url, timeout=min(5, timeout_seconds)) as response:
                    payload = json.loads(response.read())
                    if response.status != 200 or payload.get("status") != "ready":
                        still_pending.append(url)
            except OSError, ValueError, json.JSONDecodeError:
                still_pending.append(url)
        pending = tuple(still_pending)
        if not pending:
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            names = ", ".join(pending)
            raise TimeoutError(f"Hosted dependencies did not become ready: {names}")
        sleep(min(interval_seconds, remaining))


def main() -> None:
    load_project_environment()
    timeout_seconds = float(os.getenv("AGENTDESK_STARTUP_TIMEOUT_SECONDS", "300"))
    wait_for_dependencies(
        dependency_readiness_urls(os.environ),
        timeout_seconds=timeout_seconds,
    )
    port = int(os.getenv("PORT", "10000"))
    if port < 1 or port > 65535:
        raise ValueError("PORT must be between 1 and 65535.")
    uvicorn.run(
        "agents.coordinator.fixture_app:app",
        host="0.0.0.0",
        port=port,
    )


if __name__ == "__main__":
    main()
