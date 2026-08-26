# Hosted staging deployment

AgentDesk's staging target is Render, defined declaratively by the root [`render.yaml`](../render.yaml) Blueprint. The hosted stack runs the deterministic fixture demo: it exercises the production React, AG-UI, Coordinator, A2A, migration, and persistence boundaries without storing a model API key or calling an external research provider.

## Cost and authorization boundary

The Blueprint intentionally uses paid `starter` compute for the public web service and four private services, plus a paid `basic-256mb` PostgreSQL instance. Private services and the pre-deploy migration hook are not available on Render's free web-service tier. Review current Render pricing, set an appropriate workspace spend limit, and approve the resource summary in the Render dashboard before creation.

Repository configuration and validation do not create resources. Initial provisioning requires a Render account with access to `allenjoseph05/AgentDesk` and explicit dashboard approval, or a locally configured Render API key/CLI session. Never paste a Render API key into this repository, an issue, a PR, or chat.

## Resource topology

| Blueprint resource | Exposure | Purpose |
|---|---|---|
| `agentdesk-demo` | Public Render web service | Production static server, `/ag-ui` and `/api/sessions` proxy, managed HTTPS endpoint |
| `agentdesk-coordinator` | Private service | Fixture planner, orchestration, AG-UI projection, persistence, migration owner |
| `agentdesk-researcher` | Private service | Fixture-backed Researcher over the real A2A boundary |
| `agentdesk-analyst` | Private service | Fixture-backed Analyst and recommendation challenge over A2A |
| `agentdesk-verifier` | Private service | Fixture-backed Verifier over A2A |
| `agentdesk-postgres` | Private managed PostgreSQL | Durable sessions, runs, correlations, and artifacts |

All resources are pinned to the Frankfurt region. Only `agentdesk-demo` has a public hostname. Render terminates TLS at the web-service ingress and redirects public HTTP traffic to HTTPS; internal HTTP remains on Render's private network.

## Environment configuration

The Blueprint owns non-secret staging configuration:

| Variable | Owner | Meaning |
|---|---|---|
| `VITE_AGENTDESK_RUNTIME_MODE=demo` | Web build/runtime | Visible fixture-mode label and fixed request |
| `VITE_AGENTDESK_AG_UI_ENDPOINT=/ag-ui` | Web build | Same-origin browser endpoint |
| `AGENTDESK_COORDINATOR_HOSTPORT` | Render service reference | Private web-to-Coordinator proxy target |
| `*_AGENT_HOSTPORT` | Render service references | Private Coordinator discovery and Agent Card origins |
| `DATABASE_URL` | Render database reference | Private managed PostgreSQL connection string; runtime selects psycopg 3 |
| `AGENTDESK_AUTH_MODE=local` | Private agents | Public demo admission; specialists and Coordinator have no direct public ingress |
| `*_FIXTURE_*` and demo delays | Agent services | Golden fixture identity and recording timing |
| `AGENTDESK_STARTUP_TIMEOUT_SECONDS=300` | Coordinator | Bounded wait for all private specialists on initial rollout |

Live provider keys are absent by design. A future authenticated live deployment must use Render secret environment values (`sync: false` or dashboard-managed secrets), switch every service to its production entry point, configure browser/service authentication, and receive a separate security review.

## Safe migration behavior

`agentdesk-coordinator` owns the Blueprint `preDeployCommand`:

```text
python -m alembic upgrade head
```

Render runs this command in a one-off pre-deploy instance with the private `DATABASE_URL`. A non-zero exit blocks the new Coordinator release. Alembic revisions are forward-only during deploy; rollback means redeploying the previous application image against the already-upgraded compatible schema, not automatically downgrading data.

The command is idempotent at the current head and runs before the service starts accepting traffic. It is never concatenated with the web start command, so a failed migration cannot be hidden by a successful server process.

## Provision from the dashboard

1. Merge the reviewed Blueprint into the deployment branch (normally `main`).
2. Sign in to the [Render dashboard](https://dashboard.render.com/) and connect the GitHub repository if it is not already authorized.
3. Create a new Blueprint and select `allenjoseph05/AgentDesk`. Render detects `render.yaml`.
4. Review all six resources, paid instance types, Frankfurt placement, and the estimated monthly charge. Set a workspace spend limit where appropriate.
5. Approve creation. Do not add an OpenAI key; this deployment is fixture-only.
6. Wait for the three specialists to become healthy, the Coordinator migration and startup gate to pass, and `agentdesk-demo` to become healthy.
7. Record the generated `https://*.onrender.com` URL in the deployment evidence below and verify it using the checklist.

`autoDeployTrigger: checksPass` prevents later deploys from starting until the linked GitHub commit checks succeed.

## Verification checklist

- [ ] The public URL uses `https://` and an HTTP request redirects to HTTPS.
- [ ] `GET /healthz` returns `200` without exposing private service details.
- [ ] The page displays **Fixture demo** and the fixed PostgreSQL-versus-MongoDB question.
- [ ] Research completes through Researcher, Analyst, and Verifier with persisted evidence.
- [ ] The recommendation challenge renders **Strongest alternative: MongoDB**.
- [ ] Browser developer tools show `/ag-ui` on the same public origin; no specialist, Coordinator, or database hostname is public.
- [ ] Render events show the Alembic pre-deploy command completed before the Coordinator release.
- [ ] A page reload can rehydrate the durable session.

## Deployment evidence

- Public staging URL: _pending initial authorized provisioning_
- Verified commit: _pending initial authorized provisioning_
- Verified at: _pending initial authorized provisioning_

These fields are updated in the deployment story only after the real hosted checks pass. A Blueprint validation or local container run is not a substitute for a public TLS URL.

## Operations and teardown

- Inspect service events and logs from the Render dashboard. Correlate failures using safe run, session, action, remote-task, trace, and span IDs.
- Roll back a failed application release from the service Events page. Do not issue an Alembic downgrade unless a reviewed migration explicitly supports it.
- To stop ongoing compute charges, suspend or delete all five services and the PostgreSQL instance from the Blueprint/workspace. Export any data that must be retained before deleting PostgreSQL.
- Removing `render.yaml` from Git does not itself delete existing Render resources.

The local, no-cost equivalent remains the [deterministic Compose walkthrough](./demo.md).
