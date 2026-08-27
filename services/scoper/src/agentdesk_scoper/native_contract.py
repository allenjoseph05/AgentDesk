"""Accurate A2A contract exposed by Google ADK's native bridge probe."""

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol


def create_native_agent_card(base_url: str) -> AgentCard:
    """Describe the JSON-RPC interface implemented by ADK's native bridge."""
    return AgentCard(
        name="AgentDesk ADK scoper compatibility probe",
        description="Tests the experimental ADK A2A bridge with deterministic output.",
        supported_interfaces=[
            AgentInterface(
                url=base_url.rstrip("/") + "/",
                protocol_binding=TransportProtocol.JSONRPC,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id="decision-scoping",
                name="Decision scoping",
                description="Propose bounded fields for clarifying a comparison question.",
                tags=["decision", "scoping", "intake"],
            )
        ],
    )
