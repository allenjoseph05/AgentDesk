"""Agent Card construction for the Verifier Agent."""

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol


def create_agent_card(base_url: str) -> AgentCard:
    """Describe the Verifier Agent's public A2A interface and capability."""
    interface_url = base_url.rstrip("/")
    return AgentCard(
        name="AgentDesk Verifier Agent",
        description=(
            "Checks supplied claims against their cited evidence and returns "
            "structured verification findings."
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
                id="fact-verification",
                name="Fact verification",
                description=(
                    "Verify factual claims against supplied source evidence and report "
                    "support, contradictions, and uncertainty."
                ),
                tags=["verification", "facts", "claims", "evidence"],
                examples=["Verify these claims against the attached evidence bundle."],
            )
        ],
    )
