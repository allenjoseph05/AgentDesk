# ADR 0002: Use AG-UI for browser interaction

- Status: Accepted
- Date: 2026-08-17
- Stories: AD-006, AD-114
- Supersedes: the A2UI frontend protocol, renderer, and sanitizer decisions in [ADR 0001](./0001-protocol-versions.md)

## Context

ADR 0001 selected A2A for service-to-service collaboration and A2UI for a proposed generative browser interface. The vertical slice showed that AgentDesk's actual browser requirements are run lifecycle, user messages, streamed semantic progress, shared application state, cancellation, errors, reconnection, and typed follow-up actions. Those are interaction-protocol concerns rather than agent-generated component-tree concerns.

Using A2UI as an additional browser payload would duplicate lifecycle/state machinery and permit a remote producer to influence component selection. The product already has a small trusted React component set that can render every supported domain state from validated data.

The specialist boundary remains different: independent services need capability discovery, task/context identity, streamed task status, typed artifacts, and remote cancellation. A2A remains appropriate there.

## Decision

AgentDesk uses two complementary protocol boundaries:

1. **AG-UI from browser to Coordinator.** The official TypeScript `HttpAgent` posts `RunAgentInput` to `POST /ag-ui`. The official Python encoder returns ordered Server-Sent Events for run lifecycle, semantic steps, activities, text, state snapshots/deltas, errors, and the terminal outcome.
2. **A2A from Coordinator to specialists.** The Coordinator discovers validated Agent Cards and uses A2A HTTP+JSON/REST with SSE for remote tasks, typed artifacts, task/context correlation, and cancellation.
3. **Protocol-neutral domain and persistence models.** Pydantic domain artifacts are validated and committed before they are projected to AG-UI. A2A SDK objects and AG-UI events are adapter concerns, not the database model.
4. **Trusted React rendering.** The web application selects repository-owned components from runtime-validated `AgentDeskViewState`. Agents cannot provide component names, HTML, JavaScript, arbitrary props, or render trees.

A2UI packages, renderer entry points, protocol messages, and the DOMPurify override that existed only for the A2UI dependency graph are removed from the running application.

## Version baseline

| Concern | Selected baseline | Repository convention |
|---|---|---|
| AG-UI TypeScript SDK | `@ag-ui/client` 0.0.58 and `@ag-ui/core` 0.0.58 | Exact dependencies in `apps/web/package.json` |
| AG-UI Python SDK | `ag-ui-protocol` 0.1.20 | Exact dependency in `pyproject.toml` and `requirements.lock` |
| AG-UI transport | HTTP POST with SSE response | Official `HttpAgent` and Python `EventEncoder` |
| AgentDesk state/action schema | `1.0` | Strict Python contracts mirrored and runtime-validated in TypeScript |
| A2A | Protocol 1.0; `a2a-sdk[fastapi]` 1.1.2 | Retained from ADR 0001; HTTP+JSON/REST with SSE |
| React/Vite/runtime pins | ADR 0001 baseline and committed lockfiles | Unchanged by this decision |

SDK package versions, A2A protocol versions, and AgentDesk application-schema versions are independent. Upgrading one does not implicitly upgrade another.

## Required invariants

- Every accepted AG-UI run starts with `RUN_STARTED` and ends with exactly one `RUN_FINISHED` or `RUN_ERROR`; no events follow the terminal event.
- A `STATE_SNAPSHOT` establishes a baseline before deltas, and every RFC 6902 delta must validate and apply in order.
- `threadId` is stable across related interactions; every attempt has a new `runId`; `actionId` is the idempotency key; durable `sessionId` joins follow-ups and persisted artifacts.
- Human-readable messages and structured action payloads must agree.
- A2A context/task IDs are preserved and correlated with the AG-UI run, session, logs, and distributed trace.
- Cancellation at the browser transport propagates through the Coordinator to active A2A tasks.
- Reconnection uses a new run on the same thread and rehydrates an authoritative persisted snapshot; byte-level SSE replay is not promised.
- Prompts, secrets, raw headers, stack traces, and model chain-of-thought never enter client state or structured logs.

## Consequences

Positive consequences:

- The browser has one protocol for interactive agent lifecycle and shared state.
- Specialists stay UI-neutral, independently deployable A2A services.
- React remains deterministic, accessible, testable, and protected by a strict component/data boundary.
- Persist-before-project semantics make recovery independent of a particular browser stream.
- Contract tests can verify official Python encoding with the official JavaScript client.

Tradeoffs:

- Python and TypeScript maintain mirrored AgentDesk state/action schemas and cross-language fixtures.
- The Coordinator owns explicit mapping between durable workflow transitions, A2A task updates, and AG-UI events.
- The application cannot accept arbitrary agent-generated UI without a new reviewed protocol and trust-boundary decision.

## Upgrade policy

1. Use a dedicated branch and add a superseding ADR for any protocol major/minor change or trust-boundary change.
2. Review official SDK release notes and protocol migration guidance; do not infer compatibility from similarly named types.
3. Regenerate the relevant lockfile from a clean environment.
4. Run Python and TypeScript contract validation, official SDK interoperability tests, A2A send/stream/cancel integration tests, AG-UI event ordering and malformed-input suites, standard browser E2E, and the deterministic real-stack demo.
5. Keep application state schema changes explicit and versioned even when the SDK wire format is compatible.

## References

- [AgentDesk architecture guide](../architecture.md)
- [Deterministic demo walkthrough](../demo.md)
- [AG-UI documentation](https://docs.ag-ui.com/)
- [AG-UI protocol repository](https://github.com/ag-ui-protocol/ag-ui)
- [A2A 1.0 specification](https://a2a-protocol.org/latest/specification/)
