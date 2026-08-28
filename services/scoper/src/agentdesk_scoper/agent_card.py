"""A2A discovery document for the decision scoper."""

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol


def create_agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="AgentDesk Decision Scoper",
        description="Produces a validated, bounded intake proposal before research.",
        supported_interfaces=[
            AgentInterface(
                url=base_url.rstrip("/"),
                protocol_binding=TransportProtocol.HTTP_JSON,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        version="0.2.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id="decision-scoping",
                name="Decision scoping",
                description="Propose bounded fields for clarifying a comparison question.",
                tags=["decision", "scoping", "intake", "google-adk"],
            )
        ],
    )
