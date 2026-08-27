# Architecture Decision Records

Architecture decisions are numbered and immutable once accepted. A later decision records exactly which part of an earlier decision it supersedes.

- [ADR 0001: Protocol, SDK, transport, renderer, and runtime versions](./0001-protocol-versions.md) - establishes A2A and runtime pins and records the original A2UI selection.
- [ADR 0002: Use AG-UI for browser interaction](./0002-ag-ui-frontend-protocol.md) - supersedes the frontend/A2UI portion of ADR 0001 while retaining its A2A and runtime decisions.
- [ADR 0003: Add bounded A2UI intake and an isolated Google ADK scoping agent](./0003-bounded-a2ui-adk-intake.md) - retains AG-UI as the browser protocol while approving a feature-gated adaptive intake surface and isolated ADK service.
