# A2UI boundary

The Coordinator emits validated `agentdesk.a2ui.surface.v1` events for adaptive intake. This
directory owns the second, browser-side trust boundary: a strict envelope parser, the seven-component
React catalog, official A2UI message processing, bounded tree traversal, and a deterministic local
fallback. No generic or agent-defined renderer belongs here.

Only a current `awaiting_input` surface for the active session can render. Display values are literal
React text, inputs bind only to declared `/answers/<field-id>` values, and buttons map only to the
versioned submit/skip AG-UI actions. The fallback is generated from the already validated neutral
field definition, so it does not interpret a second protocol or accept arbitrary markup.
