# Work Log

Completed story records are appended here using the format required by the build specification.

## AD-001 — Initialize monorepo
Status: done
Date: 2026-08-16

Changed:
- root Python/npm workspace configuration and portable task commands
- `apps/web` React/TypeScript/Vite development shell
- Coordinator FastAPI service shell and specialist service boundaries
- shared package, infrastructure, test, and documentation boundaries
- isolated setup/development scripts and environment template

Validation:
- `npm run setup` — passed; npm audit reported zero vulnerabilities
- `npm run lint` — passed
- `npm run typecheck` — passed
- `npm test` — passed (1 Python test; frontend strict typecheck)
- `npm run build` — passed

Notes:
- A2A and A2UI packages are intentionally deferred to the version-verification ADR and protocol spikes.
- Python dependencies use bounded ranges until AD-002 records and locks the verified environment.
- npm workspaces are the cross-platform root task runner; matching Make targets are available where GNU Make exists.

## AD-002 — Create dependency pinning ADR
Status: done
Date: 2026-08-16

Changed:
- `docs/adr/0001-protocol-versions.md`
- `pyproject.toml` and `requirements.lock`
- root and web `package.json` files plus `package-lock.json`
- `.python-version` and `.nvmrc`
- `scripts/setup.py`
- protocol dependency compatibility tests and A2UI versioned import boundary

Validation:
- `npm ci` — passed; zero audit vulnerabilities
- `python scripts/setup.py` — passed using `requirements.lock`
- `npm run lint` — passed
- `npm run typecheck` — passed
- `npm test` — passed (3 Python tests; frontend strict typecheck)
- `npm run build` — passed

Notes:
- Selected A2A 1.0 with `a2a-sdk[fastapi]` 1.1.2 and HTTP+JSON/REST plus SSE.
- Selected A2UI 0.9.1 using `@a2ui/react/v0_9` 0.10.2 and `@a2ui/web_core/v0_9` 0.10.6.
- Verified the installed A2A SDK exposes `ClientFactory`, `ClientConfig`, protobuf v1 types, REST routes, and `add_a2a_routes_to_fastapi`; older `A2AFastAPIApplication` examples are not the selected 1.1.2 API.
- Overrode the A2UI Markdown package's vulnerable sanitizer pin with DOMPurify 3.4.13; clean npm installs audit with zero known vulnerabilities.
