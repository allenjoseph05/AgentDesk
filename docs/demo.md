# Deterministic demo walkthrough

This walkthrough exercises the real React, AG-UI, Coordinator, A2A, persistence, and migration boundaries without calling a model or live research provider. Fixed local fixtures make the visible workflow stable enough for a product review or screen recording.

The fixture is a functional demonstration, not a database benchmark. Its PostgreSQL recommendation and MongoDB counterargument prove the interaction path; they are not general technology advice.

## Prerequisites

- Docker with Compose v2 is running.
- Ports 5173, 8000, 8005, 8006, and 8007 are available, or their `AGENTDESK_*_PORT` equivalents are configured. PostgreSQL remains private on the Compose network.
- Node.js and installed npm dependencies are required only for the optional Playwright verification.

No OpenAI API key or external research credential is needed.

## Start from a clean checkout

From the repository root:

```powershell
Copy-Item .env.example .env
docker compose -f compose.yaml -f compose.demo.yaml up --build --wait
```

The base Compose file supplies PostgreSQL, the one-shot Alembic migration, health-gated services, and the web application. `compose.demo.yaml` explicitly replaces the production planner and specialist entry points with golden fixture providers. It also clears the Coordinator model/key settings and sets the browser mode to `demo`.

When startup succeeds, inspect the resolved service state if desired:

```powershell
docker compose -f compose.yaml -f compose.demo.yaml ps --all
```

PostgreSQL and the four agent services should be healthy, `migrate` should show a successful exit, and `web` should be healthy.

## Walkthrough

1. Open <http://localhost:5173>.
2. Confirm the **Fixture demo** badge and the notice that no live model or research provider is contacted. The fixed question is read-only: **Should the product use PostgreSQL or MongoDB?**
3. Select **Start research**. Observe real semantic phases rather than a fabricated percentage: planning, research, analysis, and verification.
4. Confirm the completed decision brief:
   - recommendation: **PostgreSQL**;
   - summary: **Relational integrity outweighs metadata flexibility.**;
   - two evidence items, including **PostgreSQL integrity fixture** and **MongoDB flexibility fixture**;
   - weighted comparison for data integrity and schema flexibility;
   - supported verification results plus the visible fixture/measurement warnings.
5. In **Challenge recommendation**, enter **What if schema flexibility matters more than relational integrity?** and select **Test counterargument**.
6. Confirm **Strongest alternative: MongoDB** and the counterargument explaining when flexible document structures outweigh relational integrity.
7. Optionally use the history sidebar to revisit the completed durable session without rerunning the specialists.

The browser action is transported through AG-UI. The Coordinator delegates each fixture-backed task over real A2A endpoints, persists accepted artifacts in PostgreSQL, and projects committed state back through the same production event path. Only provider output and fixed delays differ from live mode.

## Recording timing

The default stage delays are configured in `.env.example`:

| Stage | Variable | Default |
|---|---|---:|
| Planning | `AGENTDESK_DEMO_PLANNING_DELAY_SECONDS` | 0.35 s |
| Research | `AGENTDESK_DEMO_RESEARCH_DELAY_SECONDS` | 0.75 s |
| Analysis | `AGENTDESK_DEMO_ANALYSIS_DELAY_SECONDS` | 0.75 s |
| Verification | `AGENTDESK_DEMO_VERIFICATION_DELAY_SECONDS` | 0.5 s |

Set these values before startup to slow or accelerate a recording. The configured stage delays and fixture outputs are deterministic; first-time image pulls, container startup, browser rendering, and host load can still change total wall-clock time.

## Automated real-stack check

Keep the demo stack running, install the repository dependencies, and run:

```powershell
npm run test:e2e:demo
```

The dedicated Playwright scenario uses the actual local stack. It asserts the mode label and fixed question, completes research through verification, submits the challenge, and verifies the MongoDB counteranalysis. The standard mocked browser regression suite remains separate as `npm run test:e2e`.

## Stop and reset

Stop the temporary services while retaining PostgreSQL data:

```powershell
docker compose -f compose.yaml -f compose.demo.yaml down
```

To intentionally erase the demo database as well, append `--volumes`. Do not use that flag when the stored session history should be retained.

## Live mode

Live mode is never selected by the demo implicitly. Start the base stack without the override:

```powershell
docker compose -f compose.yaml up --build --wait
```

The browser displays **Live mode**, services use their production entry points, and the Coordinator requires its configured model/provider environment for planning. See `.env.example` for authentication, provider, model, database, and port settings.

## Troubleshooting

- If a service is unhealthy, run `docker compose -f compose.yaml -f compose.demo.yaml logs --no-color <service>` and inspect the first application error rather than repeated health probes.
- If the fixture request is rejected, confirm the browser shows **Fixture demo** and rebuild the web image; demo mode accepts only the displayed golden request.
- If Playwright cannot connect, confirm the stack is still running and `http://127.0.0.1:5173` is reachable.
- If stale local configuration selects live providers, resolve the merged Compose configuration with `docker compose -f compose.yaml -f compose.demo.yaml config` and verify the `fixture_app` commands.

The protocol and trust-boundary rationale behind this flow is shown in the [architecture guide](./architecture.md).
