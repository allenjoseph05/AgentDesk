"""Agent Card construction for the Analyst Agent."""

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol


def create_agent_card(base_url: str) -> AgentCard:
    """Describe the Analyst Agent's public A2A interface and capabilities."""
    interface_url = base_url.rstrip("/")
    return AgentCard(
        name="AgentDesk Analyst Agent",
        description=(
            "Compares options and produces evidence-bound decision analysis from "
            "evidence supplied by the coordinator."
        ),
        supported_interfaces=[
            AgentInterface(
                url=interface_url,
                protocol_binding=TransportProtocol.HTTP_JSON,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id="decision-analysis",
                name="Decision analysis",
                description=(
                    "Score named options against supplied criteria using only the provided "
                    "evidence, constraints, and decision context."
                ),
                tags=["analysis", "decisions", "scoring", "evidence"],
                examples=[
                    "Compare PostgreSQL and MongoDB using the supplied evidence bundle."
                ],
            )
        ],
    )
