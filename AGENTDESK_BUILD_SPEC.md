# AgentDesk — Senior Engineering Build Specification

**Purpose:** Delivery-ready implementation plan for an adaptive multi-agent research workspace built around A2A and A2UI.

**Primary audience:** Developer using Codex as an implementation agent.

**Planning baseline:** A2A Protocol 1.0, A2UI 0.9.1, official A2A Python SDK 1.x, React/TypeScript, Python/FastAPI, PostgreSQL.

**Document status:** Implementation baseline. Revalidate protocol/API versions before starting the build and pin exact package versions in lockfiles.

---

## 1. Executive Summary

AgentDesk is a research and decision-support workspace where a user submits an open-ended question, a coordinator delegates work to independently deployed specialist agents through A2A, and the resulting evidence, analysis, verification, and progress are progressively rendered as an interactive A2UI surface.

The project is intentionally not a conventional "multi-agent chatbot." Its value is in demonstrating four architectural properties at once:

1. **Independent agents:** specialist agents are network services with their own A2A Agent Cards, lifecycles, contracts, and failure modes.
2. **Protocol-driven orchestration:** the coordinator discovers capabilities, creates/continues A2A interactions, streams task/artifact updates, and handles cancellation and failure.
3. **Structured evidence and analysis:** agents exchange validated artifacts instead of unbounded prose blobs.
4. **Agent-driven UI:** the coordinator chooses an approved UI composition and updates its data model over time; the browser renders only trusted components from an AgentDesk catalog.

The recommended first use case is a comparison workflow such as:

> "Should our SaaS platform use PostgreSQL, MongoDB, or ClickHouse given 100k users, event ingestion, billing data, dashboards, and a small engineering team?"

That workflow naturally exercises research, parallel work, structured comparison, confidence/evidence, contradiction handling, follow-up actions, and dynamic UI.

### Recommended delivery expectation

Assuming one technically capable developer using Codex heavily, with uninterrupted access to LLM APIs and no major unfamiliarity with React/Python:

| Delivery level | Expected elapsed effort | What it means |
|---|---:|---|
| Protocol proof of concept | 3–5 working days | Two independent A2A services communicate; task + streaming demonstrated |
| Functional MVP | 15–20 working days | Coordinator + Research + Analyst + basic A2UI + one end-to-end workflow |
| Portfolio-ready v1 | 4–6 full-time weeks | Verification, polished UX, persistence, tests, tracing, deployment, demo fixtures |
| Production-style hardening | 8–12+ weeks | Strong auth, tenancy, policy, quotas, security review, operational recovery, external-agent trust |

**Planning recommendation:** commit to a **6-week portfolio-quality plan**. Aim to have the protocol-level MVP working by the end of **Week 3**. The remaining three weeks protect quality and prevent the demo from being a fragile prototype.

---

## 2. Product Vision

AgentDesk should behave like a lightweight operating environment for expert agents, not like a single chat window.

A user expresses a goal. The system decides what specialist capabilities are needed, delegates the work, keeps the user informed while work is in progress, synthesizes the outputs, and presents the result using the UI structure that best matches the problem.

### 2.1 Core user promise

> Ask one complex question. AgentDesk finds the right specialist agents, coordinates their work, shows progress, surfaces evidence and disagreement, and lets you interact with the result without requiring you to manage the agents manually.

### 2.2 Primary MVP workflow

The MVP supports **comparison research**:

- compare technologies, vendors, frameworks, databases, or architectural options;
- consider user-supplied constraints;
- collect evidence from sources;
- score options by criteria;
- surface assumptions and risks;
- produce a recommendation;
- let the user challenge the recommendation or request deeper analysis.

### 2.3 Non-goals for MVP

Do not build these initially:

- a general-purpose autonomous agent marketplace;
- arbitrary remote third-party agent execution;
- 10+ specialist agents;
- a complex vector-memory platform;
- Kubernetes, Kafka, or multi-region infrastructure;
- billing and subscription systems;
- collaborative editing;
- arbitrary agent-generated HTML/JavaScript;
- a production multi-tenant enterprise security model;
- a custom A2UI protocol implementation if an official compatible renderer is usable.

---

## 3. Success Criteria

### 3.1 MVP success criteria

The MVP is complete only when the following single workflow works end to end:

1. User submits a comparison research question.
2. Coordinator creates an A2A task/context.
3. Browser displays an A2UI research surface immediately.
4. Coordinator discovers/selects the Research Agent from an Agent Card.
5. Research Agent receives work over A2A and streams progress/artifacts.
6. Evidence appears incrementally in the browser.
7. Coordinator sends structured evidence to Analyst Agent over A2A.
8. Analyst returns a structured comparison and recommendation artifact.
9. Recommendation, comparison, assumptions, risks, and evidence render through A2UI.
10. User clicks **Challenge recommendation**.
11. Coordinator creates a follow-up analysis task in the same logical context.
12. A counterargument panel appears without a page reload.
13. User can cancel an active research session.
14. Failed remote-agent work produces a recoverable user-visible state.

### 3.2 Portfolio-quality success criteria

A reviewer should be able to verify:

- each specialist agent runs as an independently addressable service;
- the coordinator does not import specialist implementation classes;
- Agent Cards are available and used for capability discovery;
- A2A task IDs and context IDs are visible in developer/debug mode;
- streaming status or artifact events update the UI incrementally;
- only catalog-approved A2UI components are rendered;
- structured Pydantic/JSON-schema contracts exist for cross-agent artifacts;
- one agent can fail without crashing the whole system;
- cancellation is real, not just hiding a spinner;
- tests exercise protocol boundaries, artifact contracts, UI message validation, and end-to-end behavior.

### 3.3 Demo-quality success criteria

A clean demo should complete in under roughly 20 seconds when using a controlled fixture or fast model mode. The live-research mode can be slower, but the portfolio demo must be predictable.

---

## 4. Architecture

### 4.1 High-level architecture

```text
                           USER
                            │
                      React Web App
                            │
                A2A interaction + A2UI
                            │
                 ┌──────────▼──────────┐
                 │ Coordinator Agent  │
                 │ A2A Server/Client  │
                 └──────┬────┬────┬───┘
                        │    │    │
                       A2A  A2A  A2A
                        │    │    │
             ┌──────────▼┐ ┌─▼────────┐ ┌──────────▼─┐
             │ Research  │ │ Analyst  │ │ Verifier   │
             │ Agent     │ │ Agent    │ │ Agent      │
             └─────┬─────┘ └────┬─────┘ └──────┬─────┘
                   │            │              │
               tools/APIs   reasoning       sources
                   │            │              │
                   └────────────┴──────────────┘
                                │
                         structured artifacts
                                │
                         Coordinator state
                                │
                             A2UI
                                │
                         interactive surface
```

### 4.2 Responsibility boundaries

**A2A** answers:

- Which agent can perform this capability?
- How does one agent call another independent agent?
- What is the task status?
- What artifacts were produced?
- How are progress, streaming, cancellation, and context handled?

**A2UI** answers:

- What approved components should the human see?
- Which data should those components bind to?
- How should the surface update as work progresses?
- What user actions should be sent back to the agent?

**Tools/MCP/direct APIs** answer:

- How does one specialist agent obtain external information?

### 4.3 Golden architecture rule

The coordinator may know an agent's **capability contract**, but it must not depend on that agent's internal implementation.

Bad:

```python
from agents.researcher import ResearchAgent
result = await ResearchAgent().run(query)
```

Correct architectural shape:

```python
agent = registry.find_by_skill("web-research")
result = await a2a_client.send_or_stream(agent, request)
```

---

## 5. Protocol and Version Strategy

### 5.1 Initial pins

For the first implementation baseline:

- **A2A:** Protocol 1.0.
- **A2UI:** v0.9.1.
- **A2A Python SDK:** latest tested 1.x release compatible with A2A 1.0; pin exact version in `uv.lock`/`requirements.lock` after the initial spike.
- **A2UI React renderer:** pin the tested release matching the chosen protocol version.

Do not implement against `latest` tags in production code. Record exact tested versions in the repository.

### 5.2 Why version pinning is a Phase 0 requirement

Both ecosystems are evolving. A coding agent can easily mix examples from different protocol generations. The repository must therefore include an Architecture Decision Record (ADR) that identifies:

- A2A protocol version;
- Python SDK version;
- A2UI protocol version;
- renderer version;
- selected A2A transport/binding;
- known incompatibilities;
- upgrade policy.

### 5.3 Recommended A2A transport for MVP

Use **HTTP+JSON/REST with streaming where supported by the SDK**, because it is easy to inspect, test, and explain in a portfolio project. Keep the transport behind a small abstraction so it can be swapped later.

### 5.4 Agent Card strategy

Every specialist service must expose an Agent Card and advertise at least:

- identity/name;
- description;
- protocol/interface information;
- supported streaming capability;
- default input/output modes;
- skill IDs and descriptions.

The coordinator maintains a configured list of candidate agent base URLs for MVP, fetches their Agent Cards, validates them, and builds a runtime capability registry.

---

## 6. Technology Stack

### 6.1 Frontend

- React
- TypeScript
- Vite or Next.js (choose one; Vite is simpler for an SPA-style portfolio demo)
- official/compatible A2UI React renderer
- Zod for client-side validation where useful
- native `fetch`/stream helpers for A2A events
- lightweight state management only if needed; prefer local reducer/state for the first version
- Playwright for E2E
- Vitest for unit/component tests

### 6.2 Backend

- Python 3.12+
- FastAPI
- official `a2a-sdk` / A2A Python SDK
- Pydantic v2
- `httpx`
- SQLAlchemy 2.x or SQLModel
- Alembic
- PostgreSQL
- `structlog` or standard structured logging
- OpenTelemetry for traces when stable in the chosen SDK path
- `pytest`, `pytest-asyncio`

### 6.3 Optional tools

- Redis only after there is a demonstrated need for caching, task coordination, or stream fan-out.
- MCP only after the basic Research Agent works using a direct tool interface. MCP is a valuable extension, not an MVP dependency.

### 6.4 LLM provider abstraction

All agents should depend on a project-level interface:

```python
class LLMProvider(Protocol):
    async def generate_structured(
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        response_model: type[T],
    ) -> T: ...
```

Provider-specific SDK usage belongs in adapters such as:

```text
packages/llm/openai_provider.py
packages/llm/gemini_provider.py
packages/llm/fake_provider.py
```

The fake provider is mandatory for deterministic tests and demos.

---

## 7. Repository Structure

```text
agentdesk/
├── apps/
│   └── web/
│       ├── src/
│       │   ├── app/
│       │   ├── components/
│       │   ├── a2a/
│       │   │   ├── client.ts
│       │   │   ├── stream.ts
│       │   │   └── types.ts
│       │   ├── a2ui/
│       │   │   ├── catalog.ts
│       │   │   ├── registry.ts
│       │   │   ├── validators.ts
│       │   │   └── actions.ts
│       │   └── pages/
│       └── package.json
│
├── agents/
│   ├── coordinator/
│   │   ├── main.py
│   │   ├── agent_card.py
│   │   ├── executor.py
│   │   ├── planner.py
│   │   ├── registry.py
│   │   ├── orchestrator.py
│   │   ├── synthesizer.py
│   │   └── ui_composer.py
│   ├── researcher/
│   │   ├── main.py
│   │   ├── agent_card.py
│   │   ├── executor.py
│   │   ├── research.py
│   │   └── prompts.py
│   ├── analyst/
│   │   ├── main.py
│   │   ├── agent_card.py
│   │   ├── executor.py
│   │   ├── analysis.py
│   │   └── prompts.py
│   └── verifier/
│       ├── main.py
│       ├── agent_card.py
│       ├── executor.py
│       ├── verification.py
│       └── prompts.py
│
├── packages/
│   ├── contracts/
│   │   ├── research.py
│   │   ├── evidence.py
│   │   ├── analysis.py
│   │   ├── verification.py
│   │   └── ui.py
│   ├── llm/
│   ├── observability/
│   ├── persistence/
│   └── testing/
│
├── infrastructure/
│   ├── docker/
│   ├── docker-compose.yml
│   └── postgres/
│
├── tests/
│   ├── contract/
│   ├── integration/
│   └── e2e/
│
├── docs/
│   ├── adr/
│   ├── architecture.md
│   └── demo.md
│
├── .env.example
├── Makefile
├── pyproject.toml
├── package.json
└── README.md
```

### Repository rule

`packages/contracts` may be shared. Specialist business logic may not be shared with the coordinator. Shared contracts are interoperability boundaries, not a mechanism for making all services one monolith.

---

## 8. Core Domain Contracts

### 8.1 ResearchRequest

```python
class ResearchRequest(BaseModel):
    question: str
    options: list[str] = []
    constraints: list[str] = []
    criteria: list[str] = []
    desired_depth: Literal["fast", "normal", "deep"] = "normal"
```

### 8.2 Evidence

```python
class Evidence(BaseModel):
    id: str
    title: str
    source_url: str | None = None
    source_type: Literal[
        "official_documentation",
        "primary_source",
        "secondary_source",
        "user_provided",
        "fixture"
    ]
    summary: str
    relevance: float
    retrieved_at: datetime
```

### 8.3 Claim

```python
class Claim(BaseModel):
    id: str
    statement: str
    evidence_ids: list[str]
    confidence: float | None = None
    caveats: list[str] = []
```

### 8.4 EvidenceBundle

```python
class EvidenceBundle(BaseModel):
    question: str
    claims: list[Claim]
    evidence: list[Evidence]
    unknowns: list[str]
    research_notes: list[str] = []
```

### 8.5 DecisionAnalysis

```python
class CriterionScore(BaseModel):
    criterion: str
    weight: float
    scores: dict[str, float]
    rationale: str
    supporting_claim_ids: list[str]

class DecisionAnalysis(BaseModel):
    recommendation: str
    executive_summary: str
    criteria: list[CriterionScore]
    arguments_for: list[str]
    arguments_against: list[str]
    assumptions: list[str]
    risks: list[str]
    recommendation_changes_if: list[str]
```

### 8.6 VerificationReport

```python
class VerificationResult(BaseModel):
    claim_id: str
    verdict: Literal[
        "supported",
        "partially_supported",
        "contradicted",
        "insufficient_evidence"
    ]
    rationale: str
    evidence_ids: list[str]

class VerificationReport(BaseModel):
    results: list[VerificationResult]
```

### 8.7 Contract rules

- Every cross-agent structured payload must validate before use.
- Unknown fields should be rejected in core domain models unless a deliberate forward-compatibility decision is documented.
- Each artifact has a schema version.
- Each artifact includes the producing agent and task ID in envelope metadata.
- Never depend on free-form model text for workflow state transitions.

---

## 9. Coordinator State Model

```python
class ResearchSessionState(BaseModel):
    session_id: UUID
    a2a_context_id: str
    question: str

    status: Literal[
        "planning",
        "researching",
        "analyzing",
        "verifying",
        "completed",
        "cancelled",
        "failed",
        "partial"
    ]

    selected_agents: dict[str, str] = {}
    remote_task_ids: dict[str, str] = {}

    evidence: list[Evidence] = []
    claims: list[Claim] = []
    analysis: DecisionAnalysis | None = None
    verification: VerificationReport | None = None

    warnings: list[str] = []
    errors: list[str] = []

    ui_surface_id: str
```

### State transition rule

Only deterministic application code may update workflow state.

The LLM can recommend a plan, but it must not directly control network retries, task IDs, cancellation semantics, persistence transactions, or terminal workflow state.

---

## 10. Exact Request Lifecycle

### Step 1 — User submission

The browser creates a research request and sends it to the Coordinator Agent using the chosen A2A client path.

The request includes:

- the question;
- optional options/constraints;
- client capability metadata needed for A2UI;
- a client-generated request/correlation ID.

### Step 2 — Coordinator creates session

Coordinator:

1. validates input;
2. creates `research_session` row;
3. allocates an A2A context ID;
4. creates the first A2UI surface;
5. emits a visible `planning` status.

### Step 3 — Planning

Planner returns a typed plan, for example:

```json
{
  "goal": "compare_options",
  "requirements": [
    {"skill": "web-research", "scope": "collect evidence"},
    {"skill": "decision-analysis", "scope": "score options"}
  ],
  "criteria": [
    "transaction_consistency",
    "analytics",
    "operational_complexity",
    "scalability",
    "cost"
  ]
}
```

### Step 4 — Capability selection

Coordinator queries the in-memory agent registry built from validated Agent Cards.

If a required capability has no provider:

- mark the session `partial` if useful work can continue;
- otherwise fail with a clear structured error;
- never silently replace a missing specialist with unrelated coordinator behavior.

### Step 5 — Research delegation

Coordinator sends a structured research request to the Research Agent through A2A.

Coordinator persists:

- remote agent identity;
- remote task ID;
- parent research session ID;
- context ID;
- status timestamps.

### Step 6 — Streaming progress

As Research Agent emits status/artifact updates, Coordinator:

1. validates the incoming event;
2. maps protocol state to domain state;
3. persists important artifacts;
4. publishes A2UI data updates.

The browser should see meaningful progress such as:

```text
Research Agent — finding primary sources
Research Agent — 4 sources accepted
Research Agent — synthesizing claims
```

Avoid fake percentage progress unless the work has a countable denominator.

### Step 7 — Research artifact completion

Research Agent returns a validated `EvidenceBundle`.

Coordinator stores claims and evidence and emits A2UI updates for the evidence list.

### Step 8 — Analysis delegation

Coordinator sends:

- original question;
- user constraints;
- criteria;
- `EvidenceBundle`;

to Analyst Agent over A2A.

Analyst must not fetch unrelated facts during MVP. It reasons over supplied evidence. This separation makes its role testable.

### Step 9 — Analysis completion

Coordinator validates `DecisionAnalysis`, computes application-level evidence confidence indicators, persists results, and updates the A2UI data model.

### Step 10 — Optional verification

In v1, Coordinator sends claims plus evidence references to Verifier Agent.

Verifier results update badges and warnings in the surface.

### Step 11 — Final synthesis

Coordinator creates a concise synthesis that references structured analysis rather than redoing specialist reasoning from scratch.

### Step 12 — Human follow-up

User actions such as:

- `challenge_recommendation`;
- `research_deeper`;
- `focus_on_cost`;
- `retry_failed_agent`;
- `cancel_research`;

are routed back to the Coordinator as typed actions.

The same logical context is reused when the action is a continuation of the same research session.

---

## 11. A2UI Design

### 11.1 Security model

Remote or model-generated content must never result in arbitrary JavaScript/HTML execution.

The application owns a trusted catalog. Agents can request components only from that catalog.

Unknown component type -> reject.

Invalid props -> reject.

Unsafe external URL -> sanitize or render as plain text.

Unsupported catalog version -> explicit compatibility error.

### 11.2 MVP AgentDesk catalog

Implement only these components first:

- `Column`
- `Row`
- `Text`
- `Button`
- `ResearchHeader`
- `AgentStatusCard`
- `RecommendationCard`
- `ConfidenceMeter`
- `ComparisonTable`
- `EvidenceList`
- `EvidenceCard`
- `RiskCard`
- `AssumptionCard`
- `FollowUpActions`
- `ErrorNotice`

Do not add components without a real use case.

### 11.3 Surface data model

Recommended shape:

```json
{
  "research": {
    "id": "...",
    "question": "...",
    "status": "researching"
  },
  "agents": {
    "researcher": {"status": "working", "message": "..."},
    "analyst": {"status": "waiting", "message": "..."},
    "verifier": {"status": "waiting", "message": "..."}
  },
  "evidence": {
    "items": []
  },
  "analysis": {
    "recommendation": null,
    "summary": null,
    "confidence": null,
    "criteria": [],
    "risks": [],
    "assumptions": []
  },
  "verification": {
    "results": []
  },
  "actions": {
    "enabled": []
  }
}
```

### 11.4 Progressive rendering sequence

1. `createSurface`
2. initial `updateComponents`
3. `updateDataModel` with question/status
4. repeated status/evidence data updates
5. analysis updates
6. verification updates
7. action enablement
8. optional component addition for counterargument or deeper analysis

### 11.5 Design principle

Prefer a stable component tree plus frequent data updates. Recompose the component tree only when the information architecture actually changes.

---

## 12. Persistence Model

### 12.1 `research_sessions`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | Internal session ID |
| user_id | UUID/null | Optional for MVP |
| question | text | Original question |
| status | varchar/enum | Domain workflow state |
| a2a_context_id | text | Logical A2A context |
| ui_surface_id | text | A2UI surface |
| created_at | timestamptz | |
| updated_at | timestamptz | |
| completed_at | timestamptz/null | |

### 12.2 `agent_tasks`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | Internal |
| research_session_id | UUID FK | Parent session |
| agent_name | text | Selected agent |
| agent_url | text | Useful for tracing |
| remote_task_id | text/null | A2A task ID |
| status | text | Mapped status |
| started_at | timestamptz | |
| completed_at | timestamptz/null | |
| error_code | text/null | |
| error_message | text/null | Safe user-readable detail |

### 12.3 `evidence`

| Column | Type |
|---|---|
| id | UUID PK |
| research_session_id | UUID FK |
| external_evidence_id | text |
| title | text |
| source_url | text/null |
| source_type | text |
| summary | text |
| relevance | numeric |
| verification_status | text/null |
| created_at | timestamptz |

### 12.4 `claims`

| Column | Type |
|---|---|
| id | UUID PK |
| research_session_id | UUID FK |
| external_claim_id | text |
| statement | text |
| confidence | numeric/null |
| verification_status | text/null |

### 12.5 `analysis_results`

Use typed columns for searchable primary fields and JSONB for nested secondary structures.

Do not store model chain-of-thought. Persist final artifacts, decisions, state transitions, source references, and safe diagnostic metadata.

---

# 13. Delivery Roadmap — Epics

The backlog below is intentionally sequenced. Codex should not jump directly to the UI or the verifier before the A2A protocol spike is proven.

## Epic E0 — Repository, Protocol Spike, and Architecture Baseline

**Goal:** Prove the selected A2A/A2UI versions and establish the repo so all later work is built on tested assumptions.

**Exit criteria:** two minimal independent A2A services communicate successfully; exact dependency versions are pinned; ADRs exist; CI can lint and test both Python and TypeScript workspaces.

### AD-001 — Initialize monorepo

**Estimate:** 0.5 day  
**Dependencies:** none

**Acceptance criteria:**

- [ ] Repository structure matches the agreed monorepo boundaries.
- [ ] Python workspace starts with one command.
- [ ] Web workspace starts with one command.
- [ ] `.env.example` exists and contains no secrets.
- [ ] root `Makefile` or task runner provides `setup`, `lint`, `test`, `dev` targets.
- [ ] README contains local bootstrap instructions.

### AD-002 — Create dependency pinning ADR

**Estimate:** 0.5 day  
**Dependencies:** AD-001

**Acceptance criteria:**

- [ ] `docs/adr/0001-protocol-versions.md` exists.
- [ ] A2A protocol, SDK, transport, A2UI protocol, renderer, Python, Node versions are recorded.
- [ ] Lockfiles are committed.
- [ ] ADR documents how version upgrades will be tested.

### AD-003 — Build minimal A2A hello-agent server

**Estimate:** 0.75 day  
**Dependencies:** AD-002

**Acceptance criteria:**

- [ ] Service exposes a valid Agent Card.
- [ ] A separate client process resolves the card.
- [ ] Client sends a message through the official SDK path.
- [ ] Server returns a typed response.
- [ ] Integration test runs locally without an LLM API.

### AD-004 — Prove A2A task/streaming path

**Estimate:** 1 day  
**Dependencies:** AD-003

**Acceptance criteria:**

- [ ] A task can enter working state.
- [ ] At least two incremental updates are observed by the client.
- [ ] Final artifact/status is observed.
- [ ] Cancellation behavior is explored and documented.
- [ ] Protocol event fixture is saved for later frontend testing.

### AD-005 — A2UI renderer spike

**Estimate:** 1 day  
**Dependencies:** AD-001, AD-002

**Acceptance criteria:**

- [ ] React app renders one A2UI surface from a local fixture.
- [ ] A data-model update changes visible content without remounting the app shell.
- [ ] Unknown component rejection behavior is tested.
- [ ] Selected renderer version is pinned.

---

## Epic E1 — Shared Contracts and Deterministic Test Infrastructure

**Goal:** Create typed payloads before writing agent prompts.

**Exit criteria:** all agent inputs/outputs have Pydantic models and JSON fixtures; a fake LLM provider can drive deterministic tests.

### AD-010 — Implement domain Pydantic models

**Estimate:** 1 day  
**Dependencies:** E0

**Acceptance criteria:**

- [ ] `ResearchRequest`, `Evidence`, `Claim`, `EvidenceBundle`, `DecisionAnalysis`, `VerificationReport` exist.
- [ ] Models reject malformed required fields.
- [ ] Schema version is included in artifact envelopes.
- [ ] Unit tests cover valid and invalid examples.

### AD-011 — Add artifact envelope and provenance metadata

**Estimate:** 0.5 day  
**Dependencies:** AD-010

**Acceptance criteria:**

- [ ] Every artifact carries producer agent, remote task ID, schema version, and created timestamp.
- [ ] Provenance metadata is not mixed into domain payloads.

### AD-012 — Implement LLM provider abstraction

**Estimate:** 0.75 day  
**Dependencies:** AD-010

**Acceptance criteria:**

- [ ] No agent imports a vendor LLM SDK directly outside adapters.
- [ ] At least one real provider adapter exists.
- [ ] `FakeLLMProvider` returns deterministic typed fixtures.
- [ ] Tests can run with zero external API calls.

### AD-013 — Add fixture library

**Estimate:** 0.5 day  
**Dependencies:** AD-010

**Acceptance criteria:**

- [ ] Golden PostgreSQL-vs-MongoDB fixture exists.
- [ ] Good, partial, contradictory, and failure fixtures exist.
- [ ] Fixtures are reusable in backend and frontend tests.

---

## Epic E2 — Research Agent

**Goal:** Build the first real independent specialist service.

**Exit criteria:** Coordinator-like test client can discover Research Agent, submit a task, receive progress, and obtain a validated `EvidenceBundle`.

### AD-020 — Research Agent service shell and Agent Card

**Estimate:** 0.75 day  
**Dependencies:** E0, E1

**Acceptance criteria:**

- [ ] Research Agent is independently runnable.
- [ ] Agent Card advertises `web-research` and `source-synthesis` skills.
- [ ] Health/readiness endpoint exists outside protocol surface if needed.
- [ ] No imports from Coordinator implementation.

### AD-021 — Implement research tool interface

**Estimate:** 0.75 day  
**Dependencies:** AD-020

**Acceptance criteria:**

- [ ] Research logic depends on `SearchProvider`/`SourceProvider` abstraction.
- [ ] Fake provider supports deterministic fixtures.
- [ ] External source failures return typed errors.

### AD-022 — Implement evidence extraction/synthesis

**Estimate:** 1 day  
**Dependencies:** AD-021, AD-012

**Acceptance criteria:**

- [ ] Research request produces claims linked to evidence IDs.
- [ ] Important unknowns/caveats are preserved.
- [ ] Output validates as `EvidenceBundle`.
- [ ] No final recommendation is produced by this agent.

### AD-023 — Stream meaningful research status

**Estimate:** 0.75 day  
**Dependencies:** AD-022, AD-004

**Acceptance criteria:**

- [ ] Status updates reflect real phases, not fake percentages.
- [ ] Partial artifacts can be emitted where practical.
- [ ] Final task state is correct.

### AD-024 — Research Agent integration tests

**Estimate:** 0.5 day  
**Dependencies:** AD-023

**Acceptance criteria:**

- [ ] Agent Card discovery test passes.
- [ ] Full send/stream test passes with fake provider.
- [ ] Tool failure scenario is covered.
- [ ] Cancellation is covered if supported by the chosen SDK path.

---

## Epic E3 — Analyst Agent

**Goal:** Produce structured decision analysis from supplied evidence.

**Exit criteria:** Analyst independently receives a structured request and returns a validated `DecisionAnalysis` without fetching unrelated facts.

### AD-030 — Analyst service shell and Agent Card

**Estimate:** 0.5 day  
**Dependencies:** E1

**Acceptance criteria:**

- [ ] Independent A2A service exists.
- [ ] Agent Card advertises `decision-analysis` skill.
- [ ] Service accepts structured evidence input.

### AD-031 — Implement analysis prompt and structured output

**Estimate:** 1 day  
**Dependencies:** AD-030, AD-012

**Acceptance criteria:**

- [ ] Criteria weights and option scores are returned.
- [ ] Rationale references claim IDs where applicable.
- [ ] Assumptions, risks, arguments against, and change conditions are present.
- [ ] Unsupported facts are not introduced in fixture tests.

### AD-032 — Implement counterargument/challenge mode

**Estimate:** 0.75 day  
**Dependencies:** AD-031

**Acceptance criteria:**

- [ ] Analyst accepts a `challenge_current_recommendation` mode.
- [ ] Output identifies strongest credible case against current recommendation.
- [ ] Challenge output can be represented as a separate artifact.

### AD-033 — Analyst integration tests

**Estimate:** 0.5 day  
**Dependencies:** AD-031

**Acceptance criteria:**

- [ ] Happy-path fixture passes.
- [ ] Insufficient evidence produces appropriately cautious output.
- [ ] Invalid evidence input is rejected.

---

## Epic E4 — Coordinator, Discovery, and Orchestration

**Goal:** Turn independent agents into one deterministic workflow.

**Exit criteria:** Coordinator can discover agents, create a plan, delegate work, track tasks, collect artifacts, and synthesize a final result.

### AD-040 — Implement agent registry

**Estimate:** 1 day  
**Dependencies:** E0

**Acceptance criteria:**

- [ ] Base URLs are configuration-driven.
- [ ] Agent Cards are fetched at startup or on controlled refresh.
- [ ] Invalid cards are rejected with diagnostics.
- [ ] Registry supports lookup by skill.
- [ ] Duplicate skill providers are supported even if MVP selects the first healthy provider.

### AD-041 — Implement typed planner

**Estimate:** 1 day  
**Dependencies:** AD-012, AD-010

**Acceptance criteria:**

- [ ] Planner returns a typed plan, not free-form prose.
- [ ] Plan identifies required skills and criteria.
- [ ] Planner cannot invent unregistered service URLs.
- [ ] Invalid plans are rejected/retried with bounded attempts.

### AD-042 — Implement orchestrator task execution

**Estimate:** 1.25 days  
**Dependencies:** AD-040, AD-023, AD-033

**Acceptance criteria:**

- [ ] Remote calls go through a dedicated A2A client adapter.
- [ ] Remote task IDs are captured.
- [ ] Research and analysis dependencies are enforced.
- [ ] Timeout and transport failures become typed domain errors.
- [ ] Orchestrator contains no UI rendering code.

### AD-043 — Implement workflow state machine

**Estimate:** 1 day  
**Dependencies:** AD-042

**Acceptance criteria:**

- [ ] Legal state transitions are explicit.
- [ ] Terminal states cannot transition back to working accidentally.
- [ ] Partial completion is representable.
- [ ] State transition tests exist.

### AD-044 — Implement synthesis service

**Estimate:** 0.75 day  
**Dependencies:** AD-031, AD-043

**Acceptance criteria:**

- [ ] Synthesis uses specialist artifacts as authoritative inputs.
- [ ] It does not silently replace missing evidence.
- [ ] Final summary, recommendation, assumptions, and warnings are coherent.

### AD-045 — Implement cancellation propagation

**Estimate:** 0.75 day  
**Dependencies:** AD-042

**Acceptance criteria:**

- [ ] User cancellation marks local session cancelled.
- [ ] Active cancellable remote A2A tasks receive cancellation requests.
- [ ] Late events from cancelled work do not resurrect the session.
- [ ] UI receives final cancellation status.

---

## Epic E5 — Persistence and Recovery

**Goal:** Make sessions durable and debuggable.

**Exit criteria:** session/task/artifact data survives service restart; important state can be reconstructed.

### AD-050 — Database schema and migrations

**Estimate:** 1 day  
**Dependencies:** E1

**Acceptance criteria:**

- [ ] Tables for sessions, agent tasks, evidence, claims, analysis exist.
- [ ] Alembic migration is reproducible from empty DB.
- [ ] Useful indexes exist for session/task lookup.

### AD-051 — Repository layer

**Estimate:** 0.75 day  
**Dependencies:** AD-050

**Acceptance criteria:**

- [ ] Coordinator business logic does not issue raw SQL directly.
- [ ] Unit tests use transaction rollback or isolated database.

### AD-052 — Persist orchestrator transitions/artifacts

**Estimate:** 1 day  
**Dependencies:** AD-043, AD-051

**Acceptance criteria:**

- [ ] Session status transitions are durable.
- [ ] Remote task IDs are durable.
- [ ] Evidence and analysis artifacts are saved exactly once/idempotently.

### AD-053 — Research history read model

**Estimate:** 0.5 day  
**Dependencies:** AD-052

**Acceptance criteria:**

- [ ] Web app can list prior sessions.
- [ ] Completed session detail can be rehydrated without rerunning agents.

---

## Epic E6 — A2UI Catalog and Frontend Shell

**Goal:** Build a trusted adaptive UI renderer inside a stable application shell.

**Exit criteria:** a validated AgentDesk A2UI surface can render the complete fixture result with custom components.

### AD-060 — Build application shell

**Estimate:** 0.75 day  
**Dependencies:** AD-005

**Acceptance criteria:**

- [ ] Sidebar/history area exists.
- [ ] Research input exists.
- [ ] Main A2UI surface mount area exists.
- [ ] Loading/error boundaries exist.
- [ ] Layout works at laptop and tablet widths.

### AD-061 — Define AgentDesk A2UI catalog

**Estimate:** 1 day  
**Dependencies:** AD-005

**Acceptance criteria:**

- [ ] Catalog contains only MVP components.
- [ ] Each component has typed props/schema.
- [ ] Catalog version is explicit.
- [ ] Unknown component is rejected and logged.

### AD-062 — Implement research/agent-status components

**Estimate:** 0.75 day  
**Dependencies:** AD-061

**Acceptance criteria:**

- [ ] Research header and specialist statuses render from bound data.
- [ ] Working/waiting/completed/failed/cancelled visual states exist.

### AD-063 — Implement result components

**Estimate:** 1.25 days  
**Dependencies:** AD-061

**Acceptance criteria:**

- [ ] Recommendation card, comparison table, evidence list, risk and assumption components render.
- [ ] Empty and partial states are designed.
- [ ] Long evidence titles/URLs do not break layout.

### AD-064 — Implement action components

**Estimate:** 0.75 day  
**Dependencies:** AD-061

**Acceptance criteria:**

- [ ] Challenge, deeper research, retry, and cancel actions can be emitted.
- [ ] Disabled/busy state prevents duplicate submissions.
- [ ] Action payloads validate before network send.

---

## Epic E7 — End-to-End Streaming Integration

**Goal:** Make the browser reflect coordinator/agent progress in real time.

**Exit criteria:** live A2A task events produce progressive A2UI updates and a coherent final surface.

### AD-070 — Implement browser/coordinator interaction client

**Estimate:** 1 day  
**Dependencies:** E4, E6

**Acceptance criteria:**

- [ ] New research request starts a Coordinator interaction.
- [ ] Stream reconnect/failure path is defined.
- [ ] Client correlates events to the current surface/session.

### AD-071 — Implement Coordinator UI composer

**Estimate:** 1 day  
**Dependencies:** AD-043, AD-061

**Acceptance criteria:**

- [ ] Coordinator emits initial surface composition.
- [ ] Domain-state changes map to A2UI data-model updates.
- [ ] UI composer is isolated from orchestration.
- [ ] Golden A2UI fixture is snapshot-tested.

### AD-072 — Wire research progress to A2UI

**Estimate:** 0.75 day  
**Dependencies:** AD-023, AD-071

**Acceptance criteria:**

- [ ] Research status updates appear without refresh.
- [ ] Evidence can appear incrementally.
- [ ] Out-of-order duplicate events are handled idempotently where practical.

### AD-073 — Wire analysis completion to A2UI

**Estimate:** 0.5 day  
**Dependencies:** AD-031, AD-071

**Acceptance criteria:**

- [ ] Recommendation, scores, risks, assumptions render after analysis artifact.
- [ ] Partial evidence state remains visible.

### AD-074 — Implement follow-up action loop

**Estimate:** 1 day  
**Dependencies:** AD-032, AD-064, AD-070

**Acceptance criteria:**

- [ ] Challenge action creates follow-up work in same logical context.
- [ ] Counterargument UI is added/updated dynamically.
- [ ] Duplicate clicks do not create duplicate remote tasks.

---

## Epic E8 — Verification Agent

**Goal:** Add independent claim checking so AgentDesk can surface disagreement and weak support.

**Exit criteria:** verifier returns per-claim verdicts and the UI displays verification state.

### AD-080 — Verifier service shell and Agent Card

**Estimate:** 0.5 day  
**Dependencies:** E1

**Acceptance criteria:**

- [ ] Independent service.
- [ ] Agent Card advertises `fact-verification`.

### AD-081 — Implement claim verification

**Estimate:** 1 day  
**Dependencies:** AD-080, AD-012

**Acceptance criteria:**

- [ ] Every input claim receives one verdict.
- [ ] Verdict rationale references evidence IDs.
- [ ] Insufficient evidence remains a valid result, not a failure.

### AD-082 — Integrate verification into coordinator workflow

**Estimate:** 0.75 day  
**Dependencies:** AD-081, AD-043

**Acceptance criteria:**

- [ ] Verification can run after research and before/after analysis according to documented workflow.
- [ ] Verification failure does not discard successful research/analysis.

### AD-083 — Add verification UI states

**Estimate:** 0.75 day  
**Dependencies:** AD-082, AD-063

**Acceptance criteria:**

- [ ] Supported/partial/contradicted/insufficient states are visible.
- [ ] Contradictions generate a warning panel.

---

## Epic E9 — Reliability, Security, and Observability

**Goal:** Convert a happy-path demo into a credible engineering project.

### AD-090 — Structured logging and correlation IDs

**Estimate:** 0.75 day  
**Dependencies:** E4

**Acceptance criteria:**

- [ ] Every request logs session ID, context ID, trace/correlation ID, agent, remote task ID when available.
- [ ] Secrets and raw auth headers are never logged.

### AD-091 — Distributed tracing

**Estimate:** 1 day  
**Dependencies:** AD-090

**Acceptance criteria:**

- [ ] Coordinator-to-specialist calls appear as trace spans.
- [ ] A single demo request can be followed across services.
- [ ] Tracing can be disabled in local mode.

### AD-092 — Timeouts, retries, idempotency

**Estimate:** 1 day  
**Dependencies:** AD-042

**Acceptance criteria:**

- [ ] Timeouts are explicit per operation.
- [ ] Retries are bounded and only applied to safe/idempotent operations.
- [ ] Artifact ingestion is idempotent by artifact/task identifiers.
- [ ] Duplicate UI action requests are protected.

### AD-093 — A2UI validation/sanitization boundary

**Estimate:** 1 day  
**Dependencies:** AD-061

**Acceptance criteria:**

- [ ] Only registered catalog components render.
- [ ] Component payloads validate.
- [ ] Unsafe URLs/content are sanitized according to documented policy.
- [ ] Invalid message yields a safe error surface, not app crash.

### AD-094 — Service authentication baseline

**Estimate:** 1 day  
**Dependencies:** AD-042

**Acceptance criteria:**

- [ ] Browser-to-coordinator auth boundary is defined.
- [ ] Coordinator-to-agent service token or local development equivalent exists.
- [ ] Secrets come from environment/secret store, never source control.
- [ ] Auth failure has a typed non-retry loop.

### AD-095 — Rate/limit guardrails

**Estimate:** 0.75 day  
**Dependencies:** AD-094

**Acceptance criteria:**

- [ ] Per-session maximum remote tasks exists.
- [ ] Maximum research depth exists.
- [ ] LLM/tool request budget can be configured.
- [ ] User sees a useful limit-exceeded message.

---

## Epic E10 — Test Strategy and CI

**Goal:** Make the repository safe for Codex-driven iteration.

### AD-100 — Python lint/type/test pipeline

**Estimate:** 0.75 day  
**Dependencies:** E0

**Acceptance criteria:**

- [ ] Formatting/linting configured.
- [ ] Type checking configured.
- [ ] `pytest` runs all unit/contract tests.
- [ ] CI fails on lint/type/test errors.

### AD-101 — Frontend lint/type/test pipeline

**Estimate:** 0.75 day  
**Dependencies:** E6

**Acceptance criteria:**

- [ ] TypeScript strict mode enabled.
- [ ] Frontend tests run in CI.
- [ ] Catalog/schema tests included.

### AD-102 — A2A contract tests

**Estimate:** 1 day  
**Dependencies:** E2, E3, E4

**Acceptance criteria:**

- [ ] Agent Cards validate.
- [ ] send/stream path is exercised.
- [ ] task context continuity is exercised.
- [ ] cancellation path is tested.

### AD-103 — A2UI contract tests

**Estimate:** 1 day  
**Dependencies:** E6, E7

**Acceptance criteria:**

- [ ] Surface creation precedes updates.
- [ ] root component exists.
- [ ] component IDs resolve.
- [ ] only catalog components appear.
- [ ] bound data paths used by fixtures exist.

### AD-104 — Golden end-to-end test

**Estimate:** 1.25 days  
**Dependencies:** E7

**Acceptance criteria:**

- [ ] Start stack in isolated test mode.
- [ ] Submit PostgreSQL-vs-MongoDB fixture question.
- [ ] Observe researcher start and evidence.
- [ ] Observe analyst completion.
- [ ] Observe rendered recommendation.
- [ ] Click challenge action.
- [ ] Observe counterargument.
- [ ] Test produces useful failure screenshots/logs.

### AD-105 — Failure-path E2E tests

**Estimate:** 1 day  
**Dependencies:** AD-104

**Acceptance criteria:**

- [ ] Research Agent unavailable.
- [ ] Analyst timeout.
- [ ] malformed artifact.
- [ ] cancellation.
- [ ] invalid A2UI component.
- [ ] user can recover where intended.

---

## Epic E11 — Deployment, Demo, and Documentation

**Goal:** Make the project runnable by another developer and demonstrable without manual repair.

### AD-110 — Docker Compose developer stack

**Estimate:** 1 day  
**Dependencies:** E2, E3, E4, E5, E6

**Acceptance criteria:**

- [ ] `docker compose up` starts web, coordinator, researcher, analyst, verifier, postgres.
- [ ] Health checks exist.
- [ ] Startup ordering is not dependent on arbitrary sleeps.

### AD-111 — CI build and image validation

**Estimate:** 0.75 day  
**Dependencies:** AD-110, E10

**Acceptance criteria:**

- [ ] Container images build in CI.
- [ ] dependency vulnerabilities can be inspected.
- [ ] build does not include local secrets.

### AD-112 — Hosted demo deployment

**Estimate:** 1–2 days  
**Dependencies:** AD-111

**Acceptance criteria:**

- [ ] One public/staging URL serves web app.
- [ ] services use TLS through platform ingress.
- [ ] environment configuration is documented.
- [ ] database migration runs safely.

### AD-113 — Deterministic demo mode

**Estimate:** 0.75 day  
**Dependencies:** AD-013, AD-104

**Acceptance criteria:**

- [ ] Demo can run with fixture/fake provider.
- [ ] Stream timing is deterministic enough for recording.
- [ ] Live mode and fixture mode are clearly distinguished.

### AD-114 — Architecture and demo documentation

**Estimate:** 1 day  
**Dependencies:** all core epics

**Acceptance criteria:**

- [ ] README explains A2A, A2UI, and why both are used.
- [ ] architecture diagram exists.
- [ ] demo walkthrough exists.
- [ ] protocol/version ADR is linked.
- [ ] one sequence diagram shows the complete request flow.

---

# 14. Six-Week Timeline

This is the recommended portfolio-ready plan. It assumes roughly one full-time developer with Codex assisting heavily.

## Week 1 — Prove protocols and establish foundations

**Primary outcome:** no architecture speculation remains around basic A2A/A2UI integration.

**Days 1–2**

- AD-001 monorepo
- AD-002 version ADR
- AD-003 minimal A2A service/client

**Days 3–4**

- AD-004 task/streaming spike
- AD-005 A2UI renderer spike
- AD-010 domain contracts

**Day 5**

- AD-011 artifact envelope
- AD-012 LLM abstraction
- AD-013 fixtures
- CI baseline

**Week 1 gate:** Do not proceed until the independent A2A service and A2UI fixture both work.

## Week 2 — Build independent specialist agents

**Primary outcome:** Research and Analyst are real A2A services with deterministic tests.

- AD-020 through AD-024 Research Agent
- AD-030 through AD-033 Analyst Agent
- start AD-040 agent registry

**Week 2 gate:** From a standalone test client, both agents can be discovered and invoked without importing their code.

## Week 3 — Coordinator and persistence; functional MVP

**Primary outcome:** backend workflow is complete end-to-end.

- AD-040 registry
- AD-041 planner
- AD-042 orchestrator
- AD-043 state machine
- AD-044 synthesis
- AD-045 cancellation
- AD-050/051 database baseline

**Week 3 gate — MVP backend:** one request creates remote tasks, collects evidence, runs analysis, and reaches a final state.

## Week 4 — A2UI application and streaming UX

**Primary outcome:** the project becomes visually compelling.

- AD-060 shell
- AD-061 catalog
- AD-062/063/064 components/actions
- AD-070 browser interaction client
- AD-071 UI composer
- AD-072/073 live updates
- begin AD-074 follow-up loop

**Week 4 gate:** user can watch real specialist progress and see the final comparison render dynamically.

## Week 5 — Verification, resilience, and end-to-end quality

**Primary outcome:** project survives failure and demonstrates independent verification.

- complete AD-074
- AD-080 through AD-083 verifier
- AD-090 logging
- AD-092 retries/timeouts/idempotency
- AD-093 UI validation
- AD-100 through AD-105 testing

**Week 5 gate:** golden-path and failure-path E2E tests pass consistently.

## Week 6 — Security baseline, deployment, and portfolio polish

**Primary outcome:** another developer/reviewer can run it and understand it.

- AD-091 tracing
- AD-094 auth baseline
- AD-095 limits
- AD-110 Compose
- AD-111 CI images
- AD-112 hosted deployment
- AD-113 deterministic demo mode
- AD-114 README/architecture/demo docs
- UX polish and bug buffer

**Week 6 gate:** release candidate tagged `v1.0.0-demo` (or similar) and demo script works from a clean environment.

---

# 15. Critical Path

The critical path is:

```text
Version spike
  ↓
A2A streaming proof
  ↓
Contracts
  ↓
Research Agent
  ↓
Analyst Agent
  ↓
Coordinator orchestration
  ↓
A2UI catalog + composer
  ↓
End-to-end action loop
  ↓
E2E tests
  ↓
Deployment/demo
```

Persistence, verification, auth, and tracing are important but must not block proof of the fundamental A2A + A2UI loop.

### Work that can happen in parallel

After contracts are stable:

```text
Research Agent ───┐
                  ├── Coordinator integration
Analyst Agent ────┘

A2UI components ───── UI composer integration

Persistence ───────── Coordinator durability
```

If one person is implementing everything, keep one primary branch of work at a time to avoid large Codex-generated merge conflicts.

---

# 16. Effort and Capacity Model

### 16.1 Why Codex does not make the project a one-week build

Codex can substantially accelerate:

- scaffolding;
- typed models;
- repetitive SDK integration;
- tests;
- UI components;
- migrations;
- documentation.

It does not eliminate the engineering work required to:

- reconcile protocol-version differences;
- decide boundaries;
- validate A2A task semantics;
- debug streaming and cancellation;
- review generated security-sensitive code;
- verify generated UI behavior;
- test failure modes;
- make the demo reliable.

### 16.2 Suggested buffers

Reserve approximately:

- 15% integration/debugging buffer;
- 10% UX polish buffer;
- 10% dependency/version surprise buffer.

Do not schedule every day at 100% feature output.

### 16.3 Part-time estimate

At 10–15 focused hours per week, expect roughly **8–12 calendar weeks** for portfolio quality.

---

# 17. Definition of Ready

A story is ready for Codex only when:

- objective is unambiguous;
- required contract/schema exists or is part of the story;
- dependencies are complete;
- target files/modules are identifiable;
- acceptance criteria are testable;
- protocol/version assumptions are known;
- no unresolved architecture decision is hidden inside the task.

If a story is not ready, Codex should not invent architecture silently. It should document the blocking assumption in the work log and implement only the safe portion.

---

# 18. Definition of Done

A story is done only when:

- implementation is complete;
- no TODO placeholder is used to satisfy acceptance criteria;
- unit/contract tests exist where appropriate;
- tests pass locally;
- lint/type checks pass;
- public interfaces are documented;
- failure behavior is handled;
- no secret is committed;
- logging does not leak sensitive content;
- any schema change has a migration/version update;
- relevant README/ADR is updated;
- generated code has been reviewed for unnecessary complexity.

For protocol-facing changes, also require:

- fixture or integration test demonstrating the protocol behavior;
- exact version compatibility verified;
- no assumption based solely on an outdated blog example.

---

# 19. Codex Execution Instructions

This section is intentionally written as instructions to a coding agent.

## 19.1 General operating rules

1. Treat this file as the implementation source of truth unless a later ADR explicitly overrides it.
2. Execute stories in dependency order.
3. Work on one story or a very small related batch at a time.
4. Before editing code, inspect the current repository and existing tests.
5. Do not rewrite unrelated modules.
6. Do not replace an official A2A/A2UI SDK integration with a homemade approximation merely to make a test pass.
7. Never make the Coordinator directly import Research/Analyst/Verifier implementation code.
8. Shared Pydantic contracts are allowed; shared agent business logic is not.
9. Use typed structured outputs for all machine-consumed LLM responses.
10. Do not use model chain-of-thought as persisted workflow state.
11. Add or update tests in the same change as behavior.
12. Run the smallest relevant test set first, then the full validation suite.
13. If an SDK API differs from this document, verify the pinned official API, update the ADR, and adapt the code rather than guessing.
14. Prefer simple, inspectable infrastructure over abstractions that are not yet needed.
15. Keep any retry loop bounded.
16. Preserve cancellation semantics and idempotency.
17. Do not log API keys, bearer tokens, full auth headers, or hidden model reasoning.
18. Do not render arbitrary agent-provided HTML, script, or unknown UI component types.

## 19.2 Required work log format

For each completed story, add a concise entry to `docs/worklog.md`:

```text
## AD-042 — Implement orchestrator task execution
Status: done
Date: YYYY-MM-DD

Changed:
- agents/coordinator/orchestrator.py
- packages/contracts/...
- tests/integration/...

Validation:
- pytest ...
- ruff check ...
- mypy ...

Notes:
- pinned SDK behavior used
- follow-up risks/debt, if any
```

## 19.3 Commit strategy

Prefer one coherent commit per story or per tightly coupled pair of stories.

Example:

```text
feat(researcher): add A2A research task execution [AD-022]
test(a2a): cover streaming research status [AD-023]
feat(coordinator): add capability registry [AD-040]
```

Do not generate a single massive "implement AgentDesk" commit.

## 19.4 Suggested validation commands

Adapt to actual project tooling, but preserve one root-level interface:

```bash
make setup
make lint
make typecheck
make test
make test-integration
make test-e2e
make dev
```

A story cannot be marked done if its relevant command is red.

---

# 20. Prompting Rules for Specialist Agents

## 20.1 Research Agent system behavior

The Research Agent must:

- acquire and structure evidence;
- prefer authoritative/primary sources when tools allow;
- link claims to evidence IDs;
- identify unknowns and caveats;
- avoid making the final product recommendation;
- return `EvidenceBundle` only for machine-consumed output.

## 20.2 Analyst Agent system behavior

The Analyst Agent must:

- reason from the supplied evidence;
- score options against supplied criteria;
- identify assumptions;
- identify strongest arguments against its conclusion;
- state conditions that would change the recommendation;
- avoid inventing unsupported external facts;
- return `DecisionAnalysis`.

## 20.3 Verifier Agent system behavior

The Verifier Agent must:

- independently inspect each claim/evidence relationship;
- return one verdict per claim;
- distinguish weak evidence from contradiction;
- never alter the original claim;
- return `VerificationReport`.

## 20.4 Coordinator system behavior

The Coordinator must:

- plan and delegate;
- prefer registered specialists for specialist capabilities;
- maintain deterministic workflow state in application code;
- synthesize specialist outputs;
- choose an approved AgentDesk UI composition;
- surface partial failure and uncertainty rather than hiding them.

---

# 21. Confidence and Evidence Scoring

Do not present raw LLM self-confidence as a calibrated probability.

If the product displays a confidence indicator, compute an application-level **evidence confidence** from explicit signals such as:

- evidence coverage;
- source quality;
- source agreement;
- verification rate;
- missing/unknown information;
- contradiction count.

Example only:

```python
score = (
    coverage * 0.30
    + source_quality * 0.20
    + agreement * 0.20
    + verification * 0.20
    + completeness * 0.10
)
```

The exact formula is a product heuristic, not a probability of truth. Label it accordingly.

---

# 22. Failure Handling Matrix

| Failure | Coordinator behavior | User-visible behavior | Retry? |
|---|---|---|---|
| Agent Card unavailable | mark agent unhealthy | capability temporarily unavailable | bounded |
| Research Agent timeout | preserve partial evidence | research incomplete + retry/continue | yes |
| Analyst timeout | preserve research | evidence ready; analysis delayed | yes |
| Verifier failure | preserve analysis | verification unavailable | optional |
| Malformed artifact | reject artifact | specialist returned invalid result | bounded after fix/retry |
| Invalid A2UI payload | reject message | safe rendering error | no blind retry |
| User cancellation | propagate to active tasks | cancelled | no |
| Auth failure | stop request | authentication/configuration error | no loop |
| LLM quota/rate limit | mark blocked/partial | temporarily unavailable | bounded/backoff |
| DB transient error | retry safe transaction | service temporarily unavailable | bounded |

### Failure principle

A specialist failure must not erase already-valid artifacts from other specialists.

---

# 23. Security Checklist

- [ ] Validate all A2A inputs and artifact payloads.
- [ ] Validate Agent Cards before registration.
- [ ] Use allowlisted agent URLs in MVP.
- [ ] Do not accept arbitrary user-provided internal agent URLs.
- [ ] Do not render arbitrary HTML/JS from agents.
- [ ] Use catalog allowlisting for A2UI components.
- [ ] Sanitize user-visible external links.
- [ ] Separate browser auth from service-to-service auth.
- [ ] Keep secrets in environment/secret manager.
- [ ] Redact credentials from logs.
- [ ] Set request/body size limits.
- [ ] Set remote task count and LLM/tool budgets.
- [ ] Bound retries and timeouts.
- [ ] Protect state-changing actions from duplicate execution.
- [ ] Document trust assumptions for external agents before supporting them.

---

# 24. Observability Plan

Every research operation should carry:

- `session_id`;
- `a2a_context_id`;
- `trace_id`;
- local task ID;
- remote task ID;
- agent identity.

Recommended spans:

```text
research_session
├── planning
├── agent_discovery
├── research_agent_task
│   ├── send
│   ├── stream_wait
│   └── artifact_ingest
├── analyst_agent_task
├── verifier_agent_task
├── synthesis
└── ui_publish
```

Metrics worth collecting:

- session completion rate;
- partial/failure rate;
- time to first visible update;
- time to first evidence;
- time to recommendation;
- agent error rate;
- artifact validation failures;
- average external tool/LLM calls per session.

---

# 25. Testing Pyramid

## Unit tests

Focus on:

- schema validation;
- state transitions;
- planner validation;
- registry selection;
- confidence calculation;
- UI composer mapping;
- sanitization.

## Contract tests

Focus on:

- valid Agent Cards;
- artifact schemas;
- A2A send/stream/cancel behavior;
- A2UI surface/component/data-model invariants.

## Integration tests

Run actual service processes with fake providers:

- Coordinator -> Research Agent;
- Coordinator -> Analyst Agent;
- Coordinator -> Verifier Agent;
- database persistence;
- streaming event flow.

## End-to-end tests

Browser + complete local stack + deterministic providers.

Golden scenario:

```text
submit comparison
→ research status appears
→ evidence appears
→ analysis appears
→ recommendation appears
→ challenge recommendation
→ counterargument appears
```

Failure scenarios:

```text
researcher unavailable
analyst timeout
malformed evidence artifact
invalid A2UI message
cancel while researching
```

---

# 26. Demo Scenario

Use one scripted high-signal question:

> "We are building a SaaS analytics platform with 100k users in year one, event ingestion, dashboards, financial billing data, and a small engineering team. Should PostgreSQL, MongoDB, or ClickHouse be our primary database?"

Expected UI stages:

1. Research surface appears.
2. Coordinator shows planning status.
3. Research Agent changes to working.
4. Evidence cards stream in.
5. Analyst changes from waiting to working.
6. Comparison table appears.
7. Recommendation card appears.
8. Assumptions and risks appear.
9. Verifier badges appear.
10. User clicks **Challenge recommendation**.
11. Counterargument panel appears.

The demo should visibly show task/context IDs in an optional developer panel so reviewers can distinguish real A2A coordination from ordinary function calls.

---

# 27. Release Gates

## Gate A — Protocol spike

Required before feature implementation:

- A2A Agent Card works;
- send works;
- streaming/task events work;
- A2UI fixture renders;
- exact versions pinned.

## Gate B — Backend MVP

Required before frontend polish:

- Research and Analyst are independent services;
- Coordinator orchestrates them;
- artifacts are structured;
- cancellation/failure state works;
- backend integration test passes.

## Gate C — UI MVP

Required before verifier/security expansion:

- initial surface renders;
- progressive updates work;
- final comparison works;
- challenge action works.

## Gate D — Release candidate

- golden E2E passes;
- failure-path E2E passes;
- Compose starts cleanly;
- tracing/logging works;
- docs complete;
- demo fixture works;
- no known blocker-level defects.

---

# 28. Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| A2A SDK examples differ by version | Medium | High | Phase 0 spike + ADR + lock exact versions |
| A2UI renderer/API moves | Medium | High | fixture spike + catalog wrapper + pinned dependency |
| LLM output violates schema | High | Medium | structured output + validation + bounded retry + fake fixtures |
| Streaming complexity delays frontend | Medium | High | prove stream before building app UI |
| Agent boundaries collapse into monolith | Medium | High | enforce network-only specialist invocation |
| Research quality is inconsistent | High | Medium | deterministic demo mode + source quality rules |
| Codex generates over-engineered abstractions | High | Medium | story-sized changes + architecture rules + review |
| Retry logic duplicates tasks | Medium | High | idempotency keys + bounded safe retries |
| Demo depends on live external APIs | High | High | fake/fixture demo mode |
| Security issues from generated UI | Medium | High | strict catalog + schema validation + sanitization |
| Scope creep | High | High | one comparison workflow until Gate C |

---

# 29. Architecture Decisions to Record

Create ADRs for at least:

1. Protocol and SDK version pins.
2. HTTP+JSON vs alternative A2A binding.
3. React renderer and A2UI catalog strategy.
4. Shared contract package boundaries.
5. LLM provider abstraction.
6. Persistence strategy.
7. Confidence/evidence scoring semantics.
8. Authentication boundary.
9. Deterministic demo mode.
10. External agent trust model before third-party agents are enabled.

---

# 30. Phase 2 / Post-v1 Roadmap

Only after the portfolio v1 is stable:

### Multiple competing research agents

Run two or more independent research providers and display agreement/disagreement.

### Dynamic agent marketplace/registry

Allow administrators to register additional A2A agent endpoints and capabilities.

### MCP-enabled specialist tools

Move external search/data access behind MCP where it improves interoperability.

### Additional A2UI surfaces

- timeline;
- architecture diagram model;
- cost scenario editor;
- source graph;
- contradiction explorer;
- workflow DAG.

### Research session collaboration

Share a completed research session or invite teammates.

### Export

Generate a report from the structured final artifacts.

### Persistent preference/profile inputs

Allow optional user preferences to affect decision criteria, while keeping them explicit and editable.

---

# 31. Final MVP Scope Lock

For the first release, the scope is exactly:

**Agents**

- Coordinator
- Research
- Analyst
- Verifier (portfolio v1; may be deferred from earliest MVP)

**Workflow**

- compare 2–4 named options under user constraints

**Frontend components**

- research header
- agent status
- recommendation
- comparison table
- evidence list/cards
- risks
- assumptions
- follow-up actions
- error notice

**User actions**

- submit research
- cancel
- retry failed specialist
- challenge recommendation
- research deeper/focus criterion if time allows

**Infrastructure**

- React app
- Python A2A services
- PostgreSQL
- Docker Compose
- CI
- hosted demo

Anything else goes into the backlog after Gate D.

---

# 32. First 10 Tasks to Give Codex

If starting from an empty repository, issue these tasks in order rather than asking Codex to "build the whole app."

1. **AD-001:** scaffold the monorepo, development commands, lint/test skeletons.
2. **AD-002:** create the protocol-version ADR and pin dependencies after checking the official installed package APIs.
3. **AD-003:** implement a minimal standalone A2A hello-agent plus integration test.
4. **AD-004:** extend the spike to a task that emits at least two streaming updates and supports cancellation if the SDK path supports it.
5. **AD-005:** create the React A2UI fixture renderer and prove `createSurface` + data update behavior.
6. **AD-010:** implement shared Pydantic domain contracts with tests.
7. **AD-012:** implement the LLM provider interface and deterministic fake provider.
8. **AD-020:** scaffold Research Agent as an independent service with Agent Card.
9. **AD-022:** implement research-to-`EvidenceBundle` behavior using fixture tools first.
10. **AD-024:** add standalone A2A integration tests for Research Agent.

At that point, review architecture before continuing.

---

# 33. Sample Codex Task Prompt Template

Use a prompt like this for each story:

```text
Implement story AD-042 from AGENTDESK_BUILD_SPEC.md.

Before coding:
1. inspect the current repository and relevant ADRs;
2. identify the exact files you need to change;
3. verify the pinned A2A SDK APIs from the installed dependency/code/docs;
4. do not change unrelated architecture.

Implementation constraints:
- Coordinator must call specialists only over the A2A client boundary.
- Use existing shared contracts.
- Preserve typed errors, timeouts, task IDs, context IDs, and cancellation semantics.
- Do not add a retry loop unless the operation is safe and the retry is bounded.

Acceptance criteria:
Use the acceptance criteria under AD-042 exactly.

Validation:
Run relevant unit and integration tests, lint, and type checking.

At the end:
- summarize changed files;
- list commands run and results;
- note any deviation from the spec and why;
- update docs/worklog.md.
```

This produces much better results than "please implement the coordinator."

---

# 34. Senior-Developer Review Checklist

Before calling the project finished, review the following manually:

### Architecture

- [ ] Specialist agents are truly independent services.
- [ ] Coordinator owns orchestration, not specialist logic.
- [ ] Domain contracts are versioned and validated.
- [ ] Workflow state is deterministic application state.
- [ ] No hidden coupling through shared databases or imports.

### A2A

- [ ] Agent Cards are valid and meaningful.
- [ ] Task/context identifiers are handled consistently.
- [ ] Streaming behavior is real.
- [ ] Cancellation reaches remote tasks.
- [ ] Errors are mapped cleanly.

### A2UI

- [ ] UI is generated from allowed catalog components.
- [ ] Data updates do not require arbitrary code execution.
- [ ] Invalid/unknown messages cannot crash or compromise the app.
- [ ] Follow-up actions carry minimal typed context.

### Agents

- [ ] Researcher does not make final recommendation.
- [ ] Analyst does not silently invent evidence.
- [ ] Verifier is independent enough to disagree.
- [ ] Coordinator exposes uncertainty/partial failures.

### Quality

- [ ] deterministic E2E demo exists;
- [ ] live mode exists separately;
- [ ] no critical path depends on a flaky external API;
- [ ] tests fail meaningfully;
- [ ] clean clone can be started from documented instructions.

---

# 35. Reference Material

Use official sources as the source of truth during implementation, especially when SDK examples disagree.

- A2A Protocol specification: `https://a2a-protocol.org/latest/specification/`
- A2A 1.0 announcement/overview: `https://a2a-protocol.org/latest/announcing-1.0/`
- A2A Python SDK: `https://github.com/a2aproject/a2a-python`
- A2A Agent Card tutorial: `https://a2a-protocol.org/latest/tutorials/python/3-agent-skills-and-card/`
- A2A streaming guidance: `https://a2a-protocol.org/latest/topics/streaming-and-async/`
- A2UI home/specification: `https://a2ui.org/`
- A2UI roadmap/version status: `https://a2ui.org/roadmap/`
- A2UI custom catalog guide: `https://a2ui.org/guides/defining-your-own-catalog/`
- A2UI client setup: `https://a2ui.org/guides/client-setup/`

---

# 36. Final Recommendation

Build AgentDesk in three deliberate layers:

```text
Layer 1: prove A2A
Two independent services, Agent Cards, tasks, streams, cancellation.

Layer 2: prove orchestration
Research + Analyst + Coordinator + structured artifacts + persistence.

Layer 3: prove A2UI
Progressive research surface + follow-up actions + safe catalog.
```

Do not let Codex skip Layer 1 because the UI looks more exciting. The strongest part of this project is that a reviewer can inspect the repository and see genuine protocol boundaries, independently deployable agents, deterministic orchestration, and a safe agent-driven interface.

If the six-week plan is followed with disciplined scope, the end result should be a credible systems/AI-engineering portfolio project rather than a thin wrapper around several model calls.
