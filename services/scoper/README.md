# Isolated scoper compatibility project

This project pins and tests the dependency boundary selected for AgentDesk's future adaptive
decision-scoping agent. It is a compatibility spike, not a production service: no Coordinator route,
Compose service, model provider, credential, or hosted resource is added here.

The deterministic `FixtureScoperAgent` runs through a real Google ADK `Runner`. The native ADK A2A
bridge is retained only as executable compatibility evidence. The selected probe wraps the runner in
AgentDesk's established A2A HTTP+JSON adapter so typed DataParts, validation, timeout, and active-task
cancellation remain under application control.

From the repository root on Windows:

```powershell
uv venv services/scoper/.venv --python 3.14
uv pip sync --python services/scoper/.venv/Scripts/python.exe services/scoper/requirements.lock
services/scoper/.venv/Scripts/python.exe -m pytest services/scoper/tests
```

On Linux, use `services/scoper/.venv/bin/python` for the last two commands. Recreate the lock only
after reviewing dependency changes:

```text
uv pip compile services/scoper/pyproject.toml --universal --extra dev --output-file services/scoper/requirements.lock
```

See [the compatibility decision](../../docs/adaptive-intake-compatibility.md) for resolved versions,
conformance results, security evidence, and the rejected alternative.
