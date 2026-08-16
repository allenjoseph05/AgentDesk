# ADR 0001: Protocol, SDK, transport, renderer, and runtime versions

- Status: Accepted
- Date: 2026-08-16
- Story: AD-002

## Context

AgentDesk crosses two evolving protocol ecosystems. Examples written for older A2A or A2UI generations are often syntactically plausible but semantically incompatible with the current releases. We need one verified baseline before implementing protocol-facing code.

This decision was checked against official specifications, maintained package registries, and release notes on 2026-08-16.

## Decision

| Concern | Selected baseline | Repository pin or convention |
|---|---|---|
| A2A protocol | 1.0 (published specification 1.0.0) | Advertise and send protocol version `1.0` |
| A2A Python SDK | `a2a-sdk[fastapi]` 1.1.2 | Exact direct dependency in `pyproject.toml`; transitive environment in `requirements.lock` |
| A2A binding | HTTP+JSON/REST | Agent Card `protocolBinding` is `HTTP+JSON`; use `application/a2a+json` |
| A2A streaming | Server-Sent Events | `POST /message:stream`; consume ordered `StreamResponse` events |
| A2UI protocol | 0.9.1 | Emit the v0.9 message family with the v0.9.1 MIME/version refinements |
| A2UI React renderer | `@a2ui/react` 0.10.2 | Import only from `@a2ui/react/v0_9` |
| A2UI web core | `@a2ui/web_core` 0.10.6 | Import only from `@a2ui/web_core/v0_9` |
| React | 19.2.8 | Exact npm dependency |
| Vite | 8.0.16 | Exact npm development dependency |
| Python | 3.14.x; reference 3.14.6 | `.python-version`; project accepts `>=3.14,<3.15` |
| Node.js | 24.x LTS; reference 24.17.0 | `.nvmrc`; npm accepts compatible supported runtimes |
| Package manager | npm 10+ and pip in `.venv` | `package-lock.json` and `requirements.lock` are committed |
| DOM sanitization override | `dompurify` 3.4.13 | Root npm override for advisories affecting versions through 3.4.12 |

## Rationale

### A2A 1.0 and SDK 1.1.2

A2A 1.0 is the current stable protocol. The official Python SDK 1.1.2 explicitly implements A2A 1.0 and supports the three standard bindings on both client and server, including HTTP+JSON/REST.

SDK 1.1.2 is preferred over the first 1.0 SDK release because its patch/minor line includes task teardown and early producer-failure fixes that matter to AgentDesk's streaming and cancellation work.

### HTTP+JSON/REST with SSE

HTTP+JSON is a standard A2A binding, maps cleanly to FastAPI and `httpx`, and is straightforward to inspect in a portfolio project. The A2A 1.0 REST binding defines Server-Sent Events for `POST /message:stream`, so no custom streaming transport is required.

The Coordinator will isolate SDK calls behind a small adapter. That adapter must preserve A2A task IDs, context IDs, errors, cancellation, protocol-version headers, and stream ordering.

### A2UI 0.9.1 with the v0.9 renderer entrypoints

A2UI 0.9.1 is the current production protocol; A2UI 1.0 remains a candidate. The maintained React renderer and shared web core support the 0.9 family through explicit `/v0_9` entrypoints.

The npm package versions (`0.10.2` and `0.10.6`) are implementation release numbers, not the selected wire-protocol version. Code must use the versioned imports so the unversioned legacy/default surface cannot silently select v0.8 behavior.

## Known incompatibilities and constraints

- Do not use A2A 0.3 method names, payload shapes, or migration-era examples in new code.
- A2A protocol negotiation uses major/minor `1.0`, not the specification patch `1.0.0` or SDK version `1.1.2`.
- A2A 1.0 clients must send the `A2A-Version: 1.0` header unless the verified SDK binding handles it internally.
- HTTP+JSON streaming is SSE and must use the SDK's typed `StreamResponse` path; it is not a WebSocket protocol.
- A2UI v0.8 uses `beginRendering`/`surfaceUpdate`; AgentDesk uses v0.9 `createSurface`, `updateComponents`, and `updateDataModel`.
- A2UI v1.0 candidate features such as `actionResponse` are out of scope until the protocol and official React renderer are both stable.
- Unknown A2UI components and invalid properties remain application errors even when the renderer accepts a broader built-in catalog.
- `@a2ui/markdown-it` 0.1.1 currently declares vulnerable `dompurify` 3.4.11 exactly. The root uses npm's documented override mechanism to resolve that edge to 3.4.13. A clean install audits with zero known vulnerabilities; remove this exception when upstream publishes an equivalent patched dependency declaration.

## Lockfile policy

- Direct Python dependencies are exact in `pyproject.toml`.
- `requirements.lock` records the fully resolved Python development environment. `scripts/setup.py` installs it before installing AgentDesk itself with `--no-deps`.
- Direct npm dependencies are exact and `package-lock.json` records the full dependency graph.
- The root `dompurify` override is security-motivated and must not be removed until the maintained A2UI dependency graph resolves to an equally new or newer patched release.
- Lockfiles change only in a dedicated dependency or protocol-version story.

## Upgrade policy

1. Open a dedicated upgrade branch and supersede or amend this ADR.
2. Read the official protocol evolution/migration guides and SDK/renderer release notes.
3. Regenerate both lockfiles from a clean environment.
4. Re-run lint, type checks, unit/contract tests, the A2A send/stream/cancel integration suite, A2UI fixture tests, and the golden E2E scenario.
5. Do not merge an A2A major/minor or A2UI protocol upgrade while compatibility behavior is inferred rather than demonstrated by fixtures.

Patch upgrades may be accepted after the same relevant checks, but protocol-facing package upgrades never bypass the protocol spike tests.

## Official references

- A2A 1.0 specification: <https://a2a-protocol.org/latest/specification/>
- A2A 1.0 announcement: <https://a2a-protocol.org/latest/announcing-1.0/>
- A2A Python SDK releases: <https://github.com/a2aproject/a2a-python/releases>
- A2A Python SDK package: <https://pypi.org/project/a2a-sdk/>
- A2UI version status: <https://a2ui.org/roadmap/>
- A2UI maintained renderers: <https://a2ui.org/reference/renderers/>
- A2UI React package: <https://www.npmjs.com/package/@a2ui/react>
- A2UI web core package: <https://www.npmjs.com/package/@a2ui/web_core>
- Vite runtime requirements: <https://vite.dev/guide/>
- Python 3.14.6 release: <https://www.python.org/downloads/release/python-3146/>
- Node.js 24.17.0 LTS release: <https://nodejs.org/en/blog/release/v24.17.0>
