"""Independently deployable AgentDesk Verifier Agent."""

from agents.verifier.verification import (
    CLAIM_VERIFICATION_PROMPT,
    ClaimVerificationError,
    ClaimVerifier,
)

__all__ = [
    "CLAIM_VERIFICATION_PROMPT",
    "ClaimVerificationError",
    "ClaimVerifier",
]
