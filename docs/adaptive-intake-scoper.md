# Isolated ADK scoper implementation evidence

- Story: 3, isolated ADK scoping agent
- Status: complete
- Implemented: 2026-08-27
- Runtime pins: Google ADK 2.7.1 and A2A SDK 1.1.2

## Delivered boundary

The independently runnable `services/scoper` application owns ADK execution and exposes one
`decision-scoping` A2A 1.0 skill over HTTP+JSON. Its input is the bounded `ScopingRequest`; its only
successful domain output is a validated `ScopeProposalArtifact` with producer, remote-task, and UTC
provenance. The service binds the proposal ID and original question after ADK execution, so a model
cannot substitute either identifier.

The Story 1 adapter and native-bridge probes remain in place as compatibility evidence. The
production entry point is `agentdesk_scoper.main:app`. No Coordinator route, database migration,
A2UI compiler, Compose service, or hosted resource is included in this story.

## Modes and cost boundary

`fixture` is the default mode. It loads one of the three contract-validated golden proposals and
runs a deterministic ADK `BaseAgent` through ADK sessions and `Runner`. Construction and execution
do not create a model client, inspect `GOOGLE_API_KEY`, or access the network. Local development, CI,
the portfolio demo, and the committed eval suite therefore remain free and reproducible.

`live` is a separate opt-in mode. It constructs a single-turn `LlmAgent` with `ScopeProposal` as its
ADK output schema, no tools or delegation, temperature zero, and a bounded output-token setting.
Readiness requires an explicit `SCOPER_MODEL` and `GOOGLE_API_KEY`; missing configuration returns 503
without disclosing which credential value was supplied. No live request was made in Story 3. Model
selection, account creation, spend, and live benchmark execution require later explicit approval.

## Resilience and observability

- Each ADK attempt has a configurable deadline capped at 120 seconds.
- The default and evaluation profile makes one attempt. Only an explicit value of two enables a
  single retry, with a bounded delay.
- Schema failures and request-binding failures are never retried.
- Active A2A cancellation cancels and awaits ADK execution before emitting the cancelled terminal
  event, preventing a late artifact.
- Invalid requests reject; timeout, invalid output, unavailable provider, and unexpected provider
  failures fail closed with stable user messages.
- OpenTelemetry spans and structured events contain only mode, outcome, attempt, error code, and
  bounded correlation identifiers. The API has no field for questions, prompts, responses, headers,
  credentials, reasoning, or raw artifacts.

## Evaluation evidence

The committed `fixture.evalset.json` is parsed with Google ADK's official `EvalSet` model. Three
domain cases—technology, travel, and procurement—load materially different golden proposal
templates, execute through a real ADK `Runner` and in-memory session, then pass the production
`ScopeProposal` validator and exact proposal/question binding checks. This is a deterministic,
provider-free contract evaluator; it does not pretend to be an LLM quality judgment.

The service tests also cover Agent Card discovery, health/readiness, a streamed A2A artifact
envelope, invalid input, timeout, explicit bounded retry, cancellation without a late artifact,
credential-independent fixture startup, live structured configuration without execution, unknown
fields, and content-free telemetry.

## Next boundary

Story 4 adds the Coordinator's prepare/submit/skip lifecycle, persistence, A2A delegation, and
deterministic `ResearchRequest` reconstruction. It should consume this service through the existing
validated A2A registry and keep the current direct workflow as its fallback. Hosted wiring remains
deferred to Story 8, where recurring infrastructure cost must be approved separately.
