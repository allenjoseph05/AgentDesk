# AgentDesk

AgentDesk is an adaptive research and decision-support workspace. A Coordinator delegates work to independently deployed specialist agents through A2A and progressively presents structured results through a trusted A2UI component catalog.

This repository is currently at **AD-001: monorepo foundation**. Protocol integrations are intentionally introduced in the gated stories that follow; the current API and web app are runnable development shells.

## Prerequisites

- Python 3.12 or newer
- Node.js 22.12 or newer
- npm 10 or newer
- Git

`make` is optional. Every root command is also exposed through npm so the project works on Windows without GNU Make.

## Bootstrap

```powershell
Copy-Item .env.example .env
npm run setup
```

The setup command creates an isolated `.venv`, installs the root Python project with development dependencies, and installs the web workspace dependencies. Root commands select the virtual environment automatically; manual activation is not required.

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

## Validation

```powershell
npm run lint
npm run typecheck
npm test
npm run build
```

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
