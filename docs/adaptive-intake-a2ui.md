# Bounded A2UI compiler and AG-UI transport evidence

- Story: Adaptive Decision Intake 5
- Status: Complete
- Protocol: A2UI 0.9.1 (`v0.9` wire family) inside AG-UI
- Runtime validator: `a2ui-core==0.1.1`

## Delivered boundary

The Coordinator compiles a validated `ScopeProposal` into one complete, deterministic intake
surface. The scoping agent never emits A2UI and cannot choose components, actions, bindings, layout,
styles, URLs, markup, or executable content. The protocol-neutral proposal remains the persistence
source of truth.

Every surface contains exactly three ordered A2UI messages:

1. `createSurface` selects `agentdesk.dev:intake-v1`.
2. `updateDataModel` initializes proposal identity and bounded answer values.
3. `updateComponents` supplies one complete reachable graph rooted at `root`.

The catalog allows only `Text`, `TextField`, `ChoicePicker`, `CheckBox`, `Column`, `Row`, and
`Button`. Inputs bind only to known `/answers/<field-id>` paths. Buttons dispatch exactly
`agentdesk.intake.submit.v1` or `agentdesk.intake.skip.v1`, with immutable session/proposal identity
and, for submit, one `/answers` binding.

## Validation and transport

Before emission, the Coordinator applies:

- the original strict `ScopeProposal` validation again;
- exact message count, order, version, surface, catalog, size, and nesting limits;
- `a2ui-core` protocol, catalog-schema, duplicate/dangling reference, cycle, orphan, and root checks;
- the repository-owned component, action, binding, identity, and component-depth allowlists; and
- a strict `A2uiSurface` AG-UI event-value contract.

The validated value is emitted as `agentdesk.a2ui.surface.v1` after the committed
`awaiting_input` state update and before `RUN_FINISHED`. A run adapter never emits the surface after a
terminal event. There is no second A2UI HTTP, SSE, or WebSocket transport.

## Rehydration and persistence

`DurableA2uiProjector` reads the active persisted proposal and recompiles the surface with the
current catalog. The AG-UI adapter uses the same projector when an `awaiting_input` state is supplied
at run admission. Neither A2UI messages nor renderer state is stored in PostgreSQL, and decided or
missing proposals cannot be rehydrated as active surfaces.

## Verification

The focused suite covers all three fixture domains, deterministic recompilation, materially distinct
forms, invalid proposals, unknown components/actions/bindings, orphan and cyclic graphs, oversized
and deeply nested payloads, durable recompilation, namespaced custom-event contents, and terminal
ordering. Existing lifecycle tests also prove that proposal persistence precedes state and A2UI
projection.

The React renderer is intentionally not part of this story. Story 6 installs the pinned renderer,
implements the accessible repository-owned component catalog and static fallback, and maps browser
events to the existing strict AG-UI submit/skip actions.
