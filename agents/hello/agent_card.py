"""Agent Card construction for the hello agent."""

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol


def create_agent_card(base_url: str) -> AgentCard:
    """Create the public A2A Agent Card for this server instance."""
    return AgentCard(
        name="AgentDesk Hello Agent",
        description="A deterministic A2A agent that returns a typed greeting.",
        supported_interfaces=[
            AgentInterface(
                url=base_url.rstrip("/"),
                protocol_binding=TransportProtocol.HTTP_JSON,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="hello",
                name="Hello",
                description="Return a deterministic greeting for the supplied text.",
                tags=["hello", "greeting"],
                examples=["Allen"],
            )
        ],
    )
