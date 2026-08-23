"""Shared Agent Card contracts for every independently runnable service."""

from __future__ import annotations

import warnings
from collections.abc import Callable

import pytest
from a2a.types import AgentCard
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol
from a2a.utils.proto_utils import validate_proto_required_fields

from agents.analyst.agent_card import create_agent_card as create_analyst_card
from agents.hello.agent_card import create_agent_card as create_hello_card
from agents.researcher.agent_card import create_agent_card as create_research_card
from agents.verifier.agent_card import create_agent_card as create_verifier_card

pytestmark = pytest.mark.a2a_contract


@pytest.mark.parametrize(
    ("factory", "expected_skills", "input_mode"),
    [
        (create_hello_card, {"hello", "stream-hello"}, "text/plain"),
        (
            create_research_card,
            {"web-research", "source-synthesis"},
            "application/json",
        ),
        (create_analyst_card, {"decision-analysis"}, "application/json"),
        (create_verifier_card, {"fact-verification"}, "application/json"),
    ],
)
def test_agent_card_is_valid_and_advertises_the_supported_contract(
    factory: Callable[[str], AgentCard],
    expected_skills: set[str],
    input_mode: str,
) -> None:
    base_url = "https://agents.example/service"
    card = factory(f"{base_url}/")

    # SDK 1.1.2 still uses protobuf's deprecated label() API internally.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        validate_proto_required_fields(card)
    round_tripped = AgentCard.FromString(card.SerializeToString())
    assert round_tripped == card
    assert card.capabilities.streaming is True
    assert card.default_input_modes == [input_mode]
    assert card.default_output_modes == [input_mode]
    assert {skill.id for skill in card.skills} == expected_skills
    assert len(card.skills) == len(expected_skills)
    assert all(skill.description and skill.tags and skill.examples for skill in card.skills)
    assert len(card.supported_interfaces) == 1
    interface = card.supported_interfaces[0]
    assert interface.url == base_url
    assert interface.protocol_binding == TransportProtocol.HTTP_JSON
    assert interface.protocol_version == PROTOCOL_VERSION_CURRENT
