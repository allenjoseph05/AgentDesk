# Trusted React intake renderer evidence

- Story: Adaptive Decision Intake 6
- Status: Complete
- A2UI protocol: 0.9.1 (`v0.9` wire family)
- Renderer lock: `@a2ui/react@0.10.2`, `@a2ui/web_core@0.10.6`

## Delivered browser boundary

The browser consumes `agentdesk.a2ui.surface.v1` only through a second strict validator. It checks
the complete envelope, byte limit, message order, versions, catalog and surface identity, inert text,
closed component properties, direct answer bindings, proposal/action identity, unique and reachable
component graph, maximum depth, and exact submit/skip action set before giving messages to A2UI.
Surfaces are accepted only while the current AG-UI state is `awaiting_input` for the same session.

The repository-owned catalog contains exactly `Text`, `TextField`, `ChoicePicker`, `CheckBox`,
`Column`, `Row`, and `Button`. It uses the official A2UI React component adapter and
`MessageProcessor`, but owns the bounded traversal of the already-complete immutable tree. This
avoids enabling general expressions, remote resources, markdown, arbitrary style, or agent-selected
components. React text escaping remains the only display path.

Fields use labels or fieldsets/legends, help descriptions, required and invalid state, visible errors,
and native keyboard controls. A render or processor failure switches to a local form derived from
the validated neutral field definition; submit and skip remain available without interpreting new
agent output.

## AG-UI action mapping

Live composer requests now use `prepare_research`; fixture demo mode intentionally retains the
direct `start_research` path. A valid A2UI submit reads only the processor's declared answer model,
normalizes a single selection to one string, omits empty optional values, validates required and
choice constraints, and creates the strict versioned `submit_intake` action. Skip creates the empty
strict `skip_intake` action. Both recheck current session/status immediately before dispatch, use the
existing single-action gate, and run through the existing authenticated AG-UI client.

## Dependency and security verification

The exact renderer versions are declared by the web workspace and anchored at the repository root
for deterministic npm override behavior. The transitive markdown renderer remains installed by
A2UI but is not invoked by the catalog. `dompurify` is overridden to `3.4.13`; the resolved graph is
deduplicated and `npm audit --audit-level=low` reports zero vulnerabilities.

Focused contract/security tests reject unknown catalogs, protocols, components, actions and
properties; active markup, URLs and dynamic display bindings; cross-session identities; orphaned or
cyclic graphs; invalid choices; and missing required values. Component tests exercise official A2UI
message processing and the exact catalog. Static rendering tests cover the accessible fallback, and
the Chromium test proves the live `prepare_research` custom-event path renders the trusted catalog
and prevents an invalid submission from crossing AG-UI. Full submit, skip, fallback, cancellation,
replay, reconnect, and history flows remain the explicit Story 7 end-to-end fixture matrix.
