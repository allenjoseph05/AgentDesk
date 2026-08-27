# Adaptive intake compatibility spike

- Story: Adaptive intake Story 1
- Status: Passed with AgentDesk A2A adapter selected
- Verified: 2026-08-27
- Product/runtime changes: none

## Decision

Use Google ADK inside the isolated decision-scoper service, but expose the service through
AgentDesk's existing A2A HTTP+JSON adapter. Do not use ADK 2.7.1's experimental native `to_a2a()`
bridge for the production scoper baseline.

This is not a rejection of ADK. The selected probe executes a deterministic custom `BaseAgent`
through an ADK `Runner`, in-memory session service, artifact service, and memory service. AgentDesk's
adapter owns only the transport and trust boundary: Agent Card, request admission, typed A2A
DataPart, timeout, cancellation, and terminal status.

## Why the native bridge was not selected

The tested native bridge has three material mismatches:

1. With A2A SDK 1.1.2 it mounts JSON-RPC routes and advertises `JSONRPC`; the existing AgentDesk
   registry and all independently deployed specialists require the A2A 1.0 `HTTP+JSON` binding.
2. Its default event converter turns ordinary ADK text output into text status/artifact parts. A
   malformed JSON-looking result therefore has no application schema-validation gate before the
   bridge can complete it. The scoper requires a validated `ScopeProposal` DataPart.
3. In the local process-level probe, an immediate deterministic custom `BaseAgent` reached the
   native request converter but did not produce response headers or a terminal stream within the
   official client's 10-second timeout. The server emitted no application exception. Because the
   integration is explicitly experimental, this unresolved behavior is sufficient to reject it for
   the baseline rather than weakening AgentDesk's transport contract.

The native bridge also implements cancellation by enqueueing a cancelled task event. The selected
adapter additionally cancels the active ADK execution task, preventing late work or artifacts.

## Selected adapter conformance

The process-level suite uses the official A2A client and separate Uvicorn process. It proves:

| Requirement | Result |
|---|---|
| A2A version and discovery | protocol 1.0 interface in the Agent Card |
| Binding | `HTTP+JSON`, matching the Coordinator registry |
| Skill | exactly `decision-scoping` |
| Send and stream | submitted task, working status, typed artifact, completed terminal status |
| Artifact boundary | JSON object emitted as an `application/json` DataPart named `scope-proposal` |
| Malformed output | rejected with failed terminal status and no artifact |
| Timeout | bounded execution fails safely and emits no artifact |
| Cancellation | active ADK task is cancelled; terminal state is cancelled; no late artifact |
| Provider use | deterministic custom ADK agent; zero model calls and zero credentials |

This probe deliberately validates only a generic JSON object. Story 2 owns the bounded
`ScopeProposal`, `ScopeField`, and `IntakeResponse` schemas and malformed fixture corpus.

## Resolved dependency boundaries

### Isolated ADK scoper

The committed `services/scoper/requirements.lock` resolves 70 packages on Python 3.14:

- `google-adk==2.7.1`
- `a2a-sdk==1.1.2`
- `pydantic==2.13.4`
- `opentelemetry-api==1.42.1`
- `opentelemetry-sdk==1.42.1`

The root application remains on OpenTelemetry 1.44.0. Keeping the scoper in its own project and
image is therefore an architectural requirement, not optional packaging hygiene. The root project
is not installed into the scoper environment.

`pip-audit` reported no known vulnerabilities for the exact scoper lock on 2026-08-27.

### A2UI Python validation

The isolated `spikes/a2ui-python` lock resolves 20 packages and proves that `a2ui-core==0.1.1`
coexists with AgentDesk's exact Pydantic 2.13.4 and OpenTelemetry 1.44.0 pins. Its executable test
accepts a v0.9 protocol envelope and rejects an unknown v1.0 envelope. The root runtime dependency is
deferred to Story 5, where the bounded compiler is introduced.

`pip-audit` reported no known vulnerabilities for this exact lock on 2026-08-27.

### A2UI React renderer

The isolated `spikes/a2ui-web` lock proves these exact packages resolve with React 19.2.8 and their
versioned v0.9 entrypoints import successfully:

- `@a2ui/react==0.10.2`
- `@a2ui/web_core==0.10.6`

The initial audit found a moderate DOMPurify XSS advisory through `@a2ui/markdown-it`. The spike pins
the patched `dompurify==3.4.13` through an npm override. The regenerated lock reports zero known
vulnerabilities. These packages remain outside the production web workspace until Story 6 adds the
trusted intake catalog.

## CI and reproduction

The `Adaptive intake compatibility` CI job creates three independent environments and never installs
ADK into the root application:

1. scoper Python lock, lint, and A2A conformance tests;
2. A2UI Python lock and protocol validation tests;
3. A2UI web lock, v0.9 import test, and npm audit.

The exact local commands are documented in `services/scoper/README.md`. No API key, billing account,
network model request, runtime route, Compose service, migration, or hosted resource is part of this
story.

## Sources

- [Google ADK A2A overview](https://github.com/google/adk-docs/blob/main/docs/a2a/index.md)
- [Google ADK A2A exposing guide](https://github.com/google/adk-docs/blob/main/docs/a2a/quickstart-exposing.md)
- [Google ADK 2.7.1 package](https://pypi.org/project/google-adk/2.7.1/)
- [A2UI renderer implementation guide](https://github.com/a2ui-project/a2ui/blob/main/docs/public/guides/renderer-development.md)
- [A2UI v0.9 protocol](https://a2ui.org/specification/v0.9-a2ui/)
- [a2ui-core 0.1.1 package](https://pypi.org/project/a2ui-core/0.1.1/)
