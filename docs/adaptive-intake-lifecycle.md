# Adaptive intake Coordinator lifecycle evidence

- Story: 4, Coordinator intake lifecycle and persistence
- Status: complete
- Implemented: 2026-08-28

## Delivered lifecycle

The Coordinator accepts three new strict AG-UI actions: `prepare_research`, `submit_intake`, and
`skip_intake`. `prepare_research` applies a deterministic completeness rule: requests that already
contain two to four unique options and at least one criterion enter the unchanged research path;
incomplete requests create a `decision-scoping` task through the validated A2A capability registry.

Successful scoping commits the typed `ScopeProposalArtifact` before transitioning the durable
session from `scoping` to `awaiting_input`. The scoping AG-UI run then finishes; the Coordinator does
not hold an HTTP connection open while waiting for a person. Submit or skip begins a new run in the
same owner-bound AG-UI thread and session, then resumes the existing planning, research, analysis,
and verification path. The original `start_research` action remains unchanged as the direct and
failure-fallback path.

## Persistence and trust boundary

Migration `20260828_0007` adds protocol-neutral `intake_proposals` and `intake_responses` tables and
the `scoping` and `awaiting_input` session states. Proposals retain the original `ScopingRequest`,
complete typed artifact and A2A task provenance. Accepted responses retain the action ID, exact
proposal/session linkage, normalized `ResearchRequest`, and decision timestamp. Skip decisions are
recorded on the immutable proposal with the trusted normalized defaults.

Submission validates owner, thread, session, proposal ID, proposal version, required fields, answer
types, allowlisted choices, and action uniqueness before research resumes. Response insertion,
normalization, and proposal acceptance share one transaction. Repository replay is exact-match only;
a stale, cross-session, or conflicting decision fails without replacing the awaiting proposal.

The deterministic compiler preserves existing request values, adds proposal suggestions and
accepted answers, normalizes duplicates, converts enabled boolean fields to their trusted labels,
and requires two to four options plus at least one criterion. All three golden domains reconstruct
their committed expected `ResearchRequest` exactly.

## A2A and recovery behavior

The Coordinator selects the scoper only by its discovered `decision-scoping` skill. A model cannot
supply a service URL. `SCOPER_AGENT_URL` optionally adds the service to the default local registry;
the existing `AGENTDESK_AGENT_ENDPOINTS` map remains the full explicit configuration mechanism.
Compose and hosted service wiring remain deferred to Story 8.

Remote task and context IDs are persisted before the proposal. Browser cancellation reaches the
active scoper A2A task, commits cancelled task/run/session state, and cannot commit a late proposal.
Scoper failure returns a stable fallback message directing the client to the existing direct form;
raw remote errors or artifacts are not projected.

## Verification evidence

Coverage includes the three-domain compiler, strict action parsing, complete-request bypass,
proposal-before-projection ordering, same-session submit and skip, response persistence, stale and
cross-session rejection, cancellation propagation, repository constraints, migration reproducibility,
and downgrade/re-upgrade drift checks. Existing Coordinator execution, AG-UI, workflow state,
persistence, and direct `start_research` suites remain unchanged and green.

Story 5 can now compile the persisted proposal into a bounded A2UI surface and emit it through the
existing AG-UI channel. No A2UI wire messages or renderer dependencies are introduced by Story 4.
