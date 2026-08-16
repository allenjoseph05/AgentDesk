from importlib.metadata import version

from a2a.client import ClientConfig, ClientFactory
from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
from a2a.types import AgentCard, StreamResponse
from a2a.utils.constants import (
    PROTOCOL_VERSION_CURRENT,
    VERSION_HEADER,
    TransportProtocol,
)


def test_a2a_sdk_matches_accepted_protocol_baseline() -> None:
    assert version("a2a-sdk") == "1.1.2"
    assert PROTOCOL_VERSION_CURRENT == "1.0"
    assert VERSION_HEADER == "A2A-Version"
    assert TransportProtocol.HTTP_JSON.value == "HTTP+JSON"


def test_verified_a2a_entrypoints_are_importable() -> None:
    config = ClientConfig(
        streaming=True,
        supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
    )

    assert config.supported_protocol_bindings == [TransportProtocol.HTTP_JSON]
    assert ClientFactory
    assert add_a2a_routes_to_fastapi
    assert AgentCard.DESCRIPTOR.full_name == "lf.a2a.v1.AgentCard"
    assert StreamResponse.DESCRIPTOR.full_name == "lf.a2a.v1.StreamResponse"
