"""Separate command-line A2A client for the hello agent."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.types import Message, Role, SendMessageRequest
from a2a.utils.constants import TransportProtocol


@dataclass(frozen=True)
class HelloReply:
    """Serializable client view of the typed A2A Message response."""

    message_id: str
    role: str
    text: str


async def send_hello(base_url: str, text: str) -> HelloReply:
    """Resolve the Agent Card and send a message with the official A2A client."""
    http_client = httpx.AsyncClient(timeout=10.0)
    client = None
    try:
        config = ClientConfig(
            streaming=False,
            httpx_client=http_client,
            supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
        )
        client = await ClientFactory(config).create_from_url(base_url.rstrip("/"))
        request = SendMessageRequest(
            message=new_text_message(text, role=Role.ROLE_USER),
        )

        response_message: Message | None = None
        async for response in client.send_message(request):
            if response.HasField("message"):
                response_message = response.message
                break

        if response_message is None:
            raise RuntimeError("Hello agent did not return an A2A Message response.")

        return HelloReply(
            message_id=response_message.message_id,
            role=Role.Name(response_message.role),
            text=get_message_text(response_message),
        )
    finally:
        if client is not None:
            await client.close()
        elif not http_client.is_closed:
            await http_client.aclose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a message to the A2A hello agent.")
    parser.add_argument("message", nargs="?", default="world")
    parser.add_argument("--base-url", default="http://127.0.0.1:8004")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reply = asyncio.run(send_hello(args.base_url, args.message))
    print(json.dumps(asdict(reply), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
