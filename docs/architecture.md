# Architecture

The normative architecture is currently defined by [`AGENTDESK_BUILD_SPEC.md`](../AGENTDESK_BUILD_SPEC.md). This document will become the reviewer-facing architecture guide in AD-114.

The foundational boundary is already represented in the repository: the Coordinator and each specialist are separate service packages, while `packages/contracts` is reserved for interoperability models rather than shared business logic.

