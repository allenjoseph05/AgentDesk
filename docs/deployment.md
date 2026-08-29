# Zero-cost on-demand hosted demo

AgentDesk's default hosted demo target is GitHub Codespaces. It runs the real Docker Compose stack
inside an ephemeral cloud development environment and publishes only the production web server
through GitHub's TLS port-forwarding boundary. It requires no cloud payment method while the owner's
included Codespaces allowance remains available.

The root [`render.yaml`](../render.yaml) remains an optional production-shaped reference. It is not
the default demo, has not been provisioned, and requires paid private services and PostgreSQL.

## What this deployment proves

The Codespaces profile uses three Compose layers:

```text
compose.yaml              production service topology and PostgreSQL
compose.demo.yaml         deterministic planner and specialist fixtures
compose.codespaces.yaml   production web server and public-port isolation
```

The resulting path remains:

```text
public TLS URL
    -> production React server and same-origin proxy
    -> Coordinator over the Compose network
    -> optional health-gated Scoper over A2A (delegation disabled)
    -> Researcher, Analyst, and Verifier over A2A
    -> PostgreSQL
```

Scoper, Researcher, Analyst, Verifier, and Coordinator run in separate containers and communicate
over the private Compose network. The Codespaces override removes their host port publications. The
scoper runs in deterministic fixture mode and is discoverable, while adaptive delegation remains
disabled. Only the web server binds to the Codespace host on loopback port `5173`; GitHub port
forwarding is the sole public ingress.

This is an on-demand portfolio/demo environment, not an always-on production deployment. It has no
uptime SLA, stops when the Codespace stops, and retains its Docker volume only while the Codespace
continues to exist. The public port must be made public again after a Codespace restart.

## Cost boundary

GitHub personal accounts include a monthly Codespaces compute and storage allowance. When an account
without a payment method exhausts its included usage, further Codespaces usage is blocked instead of
being charged. Check the current allowance on GitHub's
[included-usage page](https://docs.github.com/en/billing/reference/product-usage-included) before
starting a long-running demo, and stop the Codespace when it is not being used.

No OpenAI, Google, Render, or other provider credential is needed. Never add a cloud API key to the
repository, Codespaces secrets, terminal history, an issue, a PR, or chat for this fixture demo.

## Create the Codespace

1. Open the repository on GitHub.
2. Select **Code**, then **Codespaces**, then **Create codespace on main**. Before AD-112 is merged,
   use **New with options** and select `story/ad-112-hosted-demo` instead.
3. Keep the default two-core machine. The committed
   [dev-container configuration](../.devcontainer/devcontainer.json) requests Docker-in-Docker and
   SSH support for remote verification, forwards port `5173`, and does not start the demo
   automatically.
4. Wait until the browser editor and terminal are ready.

The dev container deliberately does not expose the port publicly or start workloads without the
owner's action.

## Start the complete demo

In the Codespaces terminal, run:

```bash
bash scripts/codespaces_demo.sh up
```

The command validates the merged Compose model, builds the Python and production web images, starts
PostgreSQL, applies every Alembic migration, waits for the scoper, three specialists, and
Coordinator, and finishes only after the production web health check succeeds.

Useful follow-up commands are:

```bash
bash scripts/codespaces_demo.sh status
bash scripts/codespaces_demo.sh logs coordinator
bash scripts/codespaces_demo.sh stop
```

`stop` retains the PostgreSQL Docker volume. Deleting or rebuilding the Codespace can remove that
volume, so the environment must not be treated as durable production storage.

## Publish the web port

GitHub forwards configured ports privately by default. After the stack is healthy:

1. Open the **PORTS** tab in the Codespaces bottom panel.
2. Find port `5173`, labelled **AgentDesk fixture demo**.
3. Right-click it and select **Port Visibility** -> **Public**.
4. Open the forwarded address, which has this shape:

   ```text
   https://<codespace-name>-5173.app.github.dev
   ```
5. On the first visit, GitHub displays a development-port safety warning. Confirm that the hostname
   matches the Codespace, then select **Continue**. Do not enter credentials or sensitive data into
   this fixture demo.

Anyone with a public forwarded-port URL can access it without GitHub authentication. Return the port
to **Private** or stop the Codespace when the demonstration ends. GitHub documents the visibility and
restart behavior in its
[port-forwarding guide](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace).

## Verification checklist

- [ ] The forwarded URL uses `https://` and is reachable in a private browser window.
- [ ] `GET /healthz` returns `200` from the production web server.
- [ ] The page displays **Fixture demo** and the fixed PostgreSQL-versus-MongoDB question.
- [ ] Research completes through Researcher, Analyst, and Verifier with persisted evidence.
- [ ] The recommendation challenge renders **Strongest alternative: MongoDB**.
- [ ] Browser developer tools show `/ag-ui` on the same public origin.
- [ ] Only port `5173` is public; Coordinator, scoper, and specialist ports remain unforwarded or private.
- [ ] `docker compose` reports PostgreSQL and the five Python services healthy.
- [ ] A page reload can rehydrate the durable session while the Codespace remains running.

## Deployment evidence

- Public demo URL: <https://agentdesk-demo-gwrv6gj46qx29qv6-5173.app.github.dev>
- Verified commit: `46fa89f8d481d011ddc8f8b1378d6fca802fe97b`
- Verified at: `2026-08-27T08:15:46Z`
- Availability: on demand; the URL is not promised while the Codespace is stopped

The public URL is runtime evidence rather than a permanent README link. For an always-available
portfolio artifact, record the deterministic walkthrough and attach screenshots or video to the
GitHub repository or release.

The existing browser test can verify either localhost or the public forwarded URL. From a shell
with the repository dependencies installed, run:

```bash
AGENTDESK_DEMO_BASE_URL=https://<codespace-name>-5173.app.github.dev npm run test:e2e:demo
```

## Troubleshooting

- If Docker is unavailable, rebuild the dev container so the committed Docker-in-Docker feature is
  installed.
- If `up` fails, run `bash scripts/codespaces_demo.sh logs` and inspect the first application error.
- If the browser cannot connect, confirm port `5173` is listed in the PORTS tab and marked Public.
- If the UI loads but research fails, check `coordinator`, then the named specialist; do not publish
  their internal ports.
- If the forwarded port disappeared after restart, run the `up` command again if needed and restore
  port `5173` to Public.
- If Codespaces quota is unavailable, use the local deterministic walkthrough in
  [demo.md](./demo.md); do not add a payment method solely for this project.

## Optional paid Render reference

[`render.yaml`](../render.yaml) describes an always-on, production-shaped Render topology with one
public managed-TLS web service, four private services, and managed PostgreSQL in Frankfurt. It also
uses a Coordinator pre-deploy migration gate and deploy-after-CI behavior. The Blueprint is retained
as reviewed infrastructure-as-code and container-build evidence, but it is not required to complete
or demonstrate AgentDesk.

Provisioning that file creates paid resources. It must never be deployed without separate explicit
cost authorization. Removing the Blueprint from Git does not delete already-created Render resources.

The Blueprint intentionally excludes the adaptive scoper. Adding another private service requires
explicit recurring-cost authorization and passing the quality gates in the
[adaptive-intake rollout runbook](./adaptive-intake-rollout.md). Local and CI users can instead run
the key-free `compose.adaptive.yaml` opt-in overlay documented there.
