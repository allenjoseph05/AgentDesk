"""Separate A2A streaming client for the hello task path."""

from __future__ import annotations

import argparse
import asyncio
import json

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_message_text, get_text_parts, new_text_message
from a2a.types import Role, SendMessageRequest, StreamResponse, TaskState
from a2a.utils.constants import TransportProtocol


def project_event(response: StreamResponse) -> dict[str, object]:
    """Project a typed protocol event into the stable frontend fixture shape."""
    event_type = response.WhichOneof("payload")
    if event_type == "task":
        return {
            "kind": "task",
            "state": TaskState.Name(response.task.status.state),
        }
    if event_type == "status_update":
        status = response.status_update.status
        return {
            "kind": "status_update",
            "state": TaskState.Name(status.state),
            "text": get_message_text(status.message) if status.HasField("message") else "",
        }
    if event_type == "artifact_update":
        artifact_event = response.artifact_update
        return {
            "kind": "artifact_update",
            "name": artifact_event.artifact.name,
            "text": "\n".join(get_text_parts(artifact_event.artifact.parts)),
            "last_chunk": artifact_event.last_chunk,
        }
    raise ValueError(f"Unexpected A2A stream event: {event_type}")


async def collect_stream(base_url: str, text: str) -> list[dict[str, object]]:
    """Resolve the card and collect one task stream through the official SDK."""
    http_client = httpx.AsyncClient(timeout=10.0)
    client = None
    try:
        config = ClientConfig(
            streaming=True,
            httpx_client=http_client,
            supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
        )
        client = await ClientFactory(config).create_from_url(base_url.rstrip("/"))
        request = SendMessageRequest(
            message=new_text_message(text, role=Role.ROLE_USER),
        )
        return [project_event(event) async for event in client.send_message(request)]
    finally:
        if client is not None:
            await client.close()
        elif not http_client.is_closed:
            await http_client.aclose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream an A2A greeting task.")
    parser.add_argument("message", nargs="?", default="stream: world")
    parser.add_argument("--base-url", default="http://127.0.0.1:8004")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(asyncio.run(collect_stream(args.base_url, args.message))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
