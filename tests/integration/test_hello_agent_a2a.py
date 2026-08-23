"""End-to-end coverage for the standalone A2A hello agent and client."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.a2a_contract


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_until_ready(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"Hello agent stopped early.\nstdout: {stdout}\nstderr: {stderr}")
        try:
            response = httpx.get(f"{base_url}/health", timeout=0.25)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise AssertionError("Hello agent did not become ready within 10 seconds.")


def test_separate_client_resolves_card_and_receives_typed_message() -> None:
    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment["HELLO_AGENT_URL"] = base_url
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "agents.hello.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_until_ready(base_url, server)
        card_response = httpx.get(f"{base_url}/.well-known/agent-card.json")
        card_response.raise_for_status()
        card = card_response.json()
        assert card["name"] == "AgentDesk Hello Agent"
        assert card["supportedInterfaces"] == [
            {
                "url": base_url,
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            }
        ]

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "agents.hello.client",
                "Allen",
                "--base-url",
                base_url,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        reply = json.loads(completed.stdout)

        assert reply["message_id"]
        assert reply["role"] == "ROLE_AGENT"
        assert reply["text"] == "Hello, Allen!"
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
