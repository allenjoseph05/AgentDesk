# Architecture

The normative architecture is currently defined by [`AGENTDESK_BUILD_SPEC.md`](../AGENTDESK_BUILD_SPEC.md). This document will become the reviewer-facing architecture guide in AD-114.

The foundational boundary is already represented in the repository: the Coordinator and each specialist are separate service packages, while `packages/contracts` is reserved for interoperability models rather than shared business logic.

The comparison workflow uses a deterministic specialist order: Research produces and durably
commits an `EvidenceBundle`, Analysis consumes that accepted bundle and commits a
`DecisionAnalysis`, then Verification evaluates the same bundle and commits a
`VerificationReport`. Verification is intentionally last so a verifier outage or invalid artifact
cannot discard successful Research or Analysis; that condition produces a partial workflow with
the earlier artifacts retained.
