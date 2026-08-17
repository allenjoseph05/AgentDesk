"""Agent Card construction for the Research Agent."""

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol


def create_agent_card(base_url: str) -> AgentCard:
    """Describe the Research Agent's public A2A interface and capabilities."""
    interface_url = base_url.rstrip("/")
    return AgentCard(
        name="AgentDesk Research Agent",
        description=(
            "Collects traceable web evidence and synthesizes source-backed claims "
            "without making the final recommendation."
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
                id="web-research",
                name="Web research",
                description=(
                    "Find and assess relevant primary and authoritative sources for a "
                    "structured research request."
                ),
                tags=["research", "web", "evidence", "sources"],
                examples=["Compare PostgreSQL and MongoDB for an audit-heavy application."],
            ),
            AgentSkill(
                id="source-synthesis",
                name="Source synthesis",
                description=(
                    "Synthesize collected sources into claims, evidence links, caveats, "
                    "and unknowns."
                ),
                tags=["research", "synthesis", "claims", "citations"],
                examples=["Summarize the evidence and preserve important uncertainties."],
            ),
        ],
    )
