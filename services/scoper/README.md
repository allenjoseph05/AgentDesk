# Isolated AgentDesk decision scoper

This service runs Google ADK behind AgentDesk's A2A HTTP+JSON boundary and returns one validated
`ScopeProposalArtifact`. It is independently runnable, registered with the Coordinator, and wired
into Compose behind server and browser feature flags. It is intentionally absent from paid hosted
deployment; see the [rollout decision](../../docs/adaptive-intake-rollout.md).

Fixture mode is the default. It uses a real ADK `Runner` with a deterministic `BaseAgent`, makes no
network or model call, and does not inspect provider credentials. It is therefore the supported
local, CI, portfolio-demo, and evaluation mode with no payment account.

From the repository root on Windows:

```powershell
uv venv services/scoper/.venv --python 3.14
uv pip sync --python services/scoper/.venv/Scripts/python.exe services/scoper/requirements.lock
$env:PYTHONPATH = "services/scoper/src;."
services/scoper/.venv/Scripts/python.exe -m pytest services/scoper/tests
services/scoper/.venv/Scripts/python.exe -m uvicorn agentdesk_scoper.main:app --port 8011
```

The service exposes `/health`, `/ready`, `/.well-known/agent-card.json`, and the A2A HTTP+JSON
routes. The default fixture is selected with `SCOPER_FIXTURE_ID`; the three allowed library values
are `technology-database`, `travel-team-offsite`, and `procurement-design-laptop`.

Live mode is deliberately opt-in:

```powershell
$env:SCOPER_MODE = "live"
$env:SCOPER_MODEL = "<approved Gemini model>"
$env:GOOGLE_API_KEY = "<provider credential>"
```

Without both live values, `/ready` returns 503 and A2A work fails closed. Story 3 does not make a
live call, choose a paid model, provision an account, or store a credential. The normal attempt
budget is one; `SCOPER_MAX_ATTEMPTS=2` is the only supported retry override. Other bounded settings
are `SCOPER_TIMEOUT_SECONDS`, `SCOPER_RETRY_DELAY_SECONDS`, `SCOPER_BASE_URL`, and
`SCOPER_FIXTURE_DIRECTORY`.

The cases in `evals/fixture.evalset.json` use ADK's official `EvalSet` schema and execute through an
ADK `Runner`. Their deterministic evaluator validates the final structured contract and request
binding without an LLM judge. Live quality benchmarking and hosted deployment remain separately
approved activities because the committed fixture benchmark did not qualify the feature for
default-on rollout.

See [Story 3's service evidence](../../docs/adaptive-intake-scoper.md) and the earlier
[compatibility decision](../../docs/adaptive-intake-compatibility.md).
