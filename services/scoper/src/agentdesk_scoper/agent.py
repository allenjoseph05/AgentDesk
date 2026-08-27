"""Conventional ADK root agent used by the deterministic evaluation suite."""

from agentdesk_scoper.fixture_agent import FixtureScoperAgent
from agentdesk_scoper.fixture_library import load_fixture_proposal
from agentdesk_scoper.settings import ScoperSettings

_SETTINGS = ScoperSettings()
root_agent = FixtureScoperAgent(
    name="decision_scoper",
    description="Deterministic contract-valid decision scoper.",
    proposal_template=load_fixture_proposal(
        _SETTINGS.fixture_directory,
        _SETTINGS.fixture_id,
    ).model_dump(mode="json"),
)
