"""Compatibility checks for a2ui-core against AgentDesk's root runtime pins."""

from importlib.metadata import version

import pytest
from a2ui.core.validating import A2uiValidator, A2uiValidatorError


def test_a2ui_protocol_envelope_accepts_v09_and_rejects_unknown_versions() -> None:
    validator = A2uiValidator()
    valid_messages = [
        {
            "version": "v0.9",
            "createSurface": {
                "surfaceId": "decision-intake",
                "catalogId": "agentdesk.dev:intake-v1",
            },
        },
        {
            "version": "v0.9",
            "updateDataModel": {
                "surfaceId": "decision-intake",
                "value": {"question": "PostgreSQL or MongoDB?"},
            },
        },
    ]

    validator.validate_protocol_envelope(valid_messages)

    invalid_messages = [{**valid_messages[0], "version": "v1.0"}]
    with pytest.raises(A2uiValidatorError):
        validator.validate_protocol_envelope(invalid_messages)


def test_a2ui_core_coexists_with_agentdesk_runtime_pins() -> None:
    assert version("a2ui-core") == "0.1.1"
    assert version("pydantic") == "2.13.4"
    assert version("opentelemetry-api") == "1.44.0"
    assert version("opentelemetry-sdk") == "1.44.0"
