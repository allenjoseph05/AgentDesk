# Adaptive-intake rollout and operations

- Status: local/CI opt-in complete; hosted and default-on rollout blocked
- Last verified: 2026-08-29
- Quality decision: [`not_eligible`](./adaptive-intake-evaluation.md)

AgentDesk packages the isolated Google ADK scoper as a fifth Python service and registers it with the
Coordinator over A2A. The service is healthy in the base Compose topology, but the Coordinator's
delegation flag and the browser renderer flag both default to `false`. This separates deployment
readiness from product rollout and makes rollback a configuration change.

## Zero-cost local opt-in

The supported adaptive demo uses deterministic fixtures and needs no API key, provider account, or payment method:

```powershell
docker compose -f compose.yaml -f compose.demo.yaml -f compose.adaptive.yaml up --build --wait
```

Open `http://localhost:5173`. The adaptive overlay enables both sides of the feature boundary:

- `AGENTDESK_ADAPTIVE_SCOPING_ENABLED=true` permits the Coordinator to delegate `decision-scoping`.
- `VITE_AGENTDESK_ADAPTIVE_INTAKE_ENABLED=true` permits the trusted React catalog to render intake.
- `SCOPER_MODE=fixture` remains deterministic and ignores provider credentials.

Stop the stack with the same three files and `down`. The ordinary base, demo, and Codespaces
commands omit `compose.adaptive.yaml`, so adaptive intake stays disabled there.

## Configuration and secret boundary

| Setting | Default | Purpose |
|---|---|---|
| `AGENTDESK_ADAPTIVE_SCOPING_ENABLED` | `false` | Server-side delegation gate |
| `VITE_AGENTDESK_ADAPTIVE_INTAKE_ENABLED` | `false` | Browser-side trusted-renderer gate |
| `SCOPER_MODE` | `fixture` | Select deterministic fixture or explicitly approved live mode |
| `SCOPER_FIXTURE_ID` | `technology-database` | Select a committed fixture |
| `SCOPER_MODEL` | empty | Live-only model identifier |
| `GOOGLE_API_KEY` | empty | Live-only provider credential |

Fixture mode must remain key-free. A credential is required only if an operator separately approves
live evaluation and selects `SCOPER_MODE=live`; it must be injected by the deployment secret store,
never committed. The service fails readiness if live mode lacks its model or credential.

## Health and failure behavior

Compose starts the scoper before the Coordinator and requires `/ready` to report `status=ready` and
`mode=fixture`. The Coordinator then discovers four Agent Cards (scoper plus three specialists).
Even when the scoper is healthy, a disabled server flag rejects new adaptive preparation before any
remote task is created. Submit and skip remain accepted for already-persisted sessions after a
rollback.

Scoper failure, timeout, cancellation, invalid artifact, or stale input fails closed. The user can
continue through the existing direct/static research path; no generated UI or free-form model output
can drive workflow state.

## Content-safe dashboard contract

[`adaptive-intake-dashboard.json`](../infrastructure/observability/adaptive-intake-dashboard.json)
defines six vendor-neutral panels:

1. proposal validity;
2. intake completion versus skip;
3. fallback rate;
4. scoper latency;
5. scoper input/output token use; and
6. downstream benchmark quality.

The queries use status, error code, mode, duration, token count, and published aggregate evaluation
data. User prompts, answers, artifacts, request payloads, model responses, and A2UI surfaces are
prohibited. This repository records the dashboard contract; an operator may map it to a chosen
metrics backend without expanding the content boundary.

## Rollout gates

1. **Disabled (current default):** scoper image is built and scanned; browser and Coordinator flags
   are false.
2. **Opt-in (local/CI only):** use `compose.adaptive.yaml` with fixture mode and verify all six
   dashboard signals.
3. **Default-on (blocked):** requires a representative, explicitly approved live evaluation that
   passes every gate in the evaluation report, including at least 15% quality improvement, bounded
   latency/token use, accessibility, and no unresolved high/critical dependency or image finding.

The committed fixture scored `0.0500` against a required `0.2300`; therefore it is useful protocol
evidence but does not justify default-on or paid hosted deployment.

## Rollback

Set both feature flags to `false` and redeploy/restart the affected services. New questions use the
existing direct path immediately. Persisted proposals and accepted responses remain readable because
storage is protocol-neutral. The scoper container can be removed later without a database migration.

## Hosted boundary

`render.yaml` intentionally has no scoper service. Adding one would create another paid private
service and failure domain, so it requires explicit recurring-cost approval plus passing rollout
evidence. The zero-cost Codespaces demo also remains non-adaptive by default; its private Compose
network still exercises scoper health and Agent Card discovery without provider credentials.
