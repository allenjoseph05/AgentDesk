# AgentDesk

AgentDesk is an adaptive research and decision-support workspace. A Coordinator delegates work to independently deployed specialist agents through A2A and progressively presents structured results through a trusted A2UI component catalog.

This repository is currently at **AD-001: monorepo foundation**. Protocol integrations are intentionally introduced in the gated stories that follow; the current API and web app are runnable development shells.

## Prerequisites

- Python 3.14.x (reference version: 3.14.6)
- Node.js 24.x LTS (reference version: 24.17.0)
- npm 10 or newer
- Git

`make` is optional. Every root command is also exposed through npm so the project works on Windows without GNU Make.

## Bootstrap

```powershell
Copy-Item .env.example .env
npm run setup
```

The setup command creates an isolated `.venv`, installs the locked Python environment, and installs the locked web workspace dependencies. Root commands select the virtual environment automatically; manual activation is not required. Protocol and runtime decisions are recorded in [ADR 0001](./docs/adr/0001-protocol-versions.md).

## Development

Start the Coordinator development shell and React app together:

```powershell
npm run dev
```

The services are available at:

- Web: `http://localhost:5173`
- Coordinator health endpoint: `http://localhost:8000/health`
- Coordinator API documentation: `http://localhost:8000/docs`

Run either side independently with `npm run dev:api` or `npm run dev:web`.

### Docker Compose stack

Start the complete local stack from the repository root:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose starts PostgreSQL, applies migrations, waits for the Researcher, Analyst, and Verifier
readiness endpoints, starts the Coordinator after it can discover all three specialists, and then
starts the web app. Open `http://localhost:5173`. Stop the stack with `docker compose down`; add
`--volumes` only when you intentionally want to remove the local PostgreSQL data volume.

### Deterministic fixture demo

Start the recording-friendly demo without API keys or external providers:

```powershell
docker compose -f compose.yaml -f compose.demo.yaml up --build --wait
```

Open `http://localhost:5173` and run the prefilled PostgreSQL-versus-MongoDB question. The browser
labels this configuration **Fixture demo**, and planning, research, analysis, and verification use
fixed local data with configurable delays from `.env.example`. The default `docker compose up`
command remains **Live mode** and never selects fixture entry points implicitly.

With the demo stack healthy, its real browser path can be checked independently:

```powershell
npm run test:e2e:demo
```

## Validation

```powershell
npm run lint
npm run typecheck
npm test
npm run build
```

Python-only gates are available as `npm run lint:python`,
`npm run typecheck:python`, and `npm run test:python`. The Python lint gate runs both
Ruff diagnostics and the repository-wide Ruff formatting check.

Equivalent `make lint`, `make typecheck`, `make test`, and `make build` targets are provided for environments with GNU Make.

## Repository boundaries

- `apps/web`: React/TypeScript application and future A2A/A2UI browser adapters.
- `agents/coordinator`: Coordinator service. It may know specialist contracts, never specialist implementations.
- `agents/researcher`, `agents/analyst`, `agents/verifier`: independently deployable specialist boundaries.
- `packages/contracts`: shared interoperability contracts only.
- `packages/llm`, `packages/observability`, `packages/persistence`, `packages/testing`: shared infrastructure packages.
- `infrastructure`: local and deployment infrastructure.
- `tests`: contract, integration, and end-to-end suites.
- `docs`: ADRs, architecture notes, demo material, and the required work log.

The implementation source of truth is [`AGENTDESK_BUILD_SPEC.md`](./AGENTDESK_BUILD_SPEC.md). Protocol and dependency choices must be recorded in ADRs before A2A or A2UI feature work begins.
