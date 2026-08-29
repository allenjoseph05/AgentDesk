"""Fail-closed rollout settings for adaptive decision scoping."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

ADAPTIVE_SCOPING_ENABLED_ENV = "AGENTDESK_ADAPTIVE_SCOPING_ENABLED"


@dataclass(frozen=True)
class AdaptiveIntakeSettings:
    """Control new scoper delegation independently from browser rendering and provider mode."""

    scoping_enabled: bool = False

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> AdaptiveIntakeSettings:
        source = os.environ if environ is None else environ
        raw = source.get(ADAPTIVE_SCOPING_ENABLED_ENV, "false").strip().casefold()
        if raw not in {"true", "false"}:
            raise ValueError(f"{ADAPTIVE_SCOPING_ENABLED_ENV} must be true or false.")
        return cls(scoping_enabled=raw == "true")
