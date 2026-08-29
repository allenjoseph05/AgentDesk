import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import test from "node:test";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const webRoot = fileURLToPath(new URL("..", import.meta.url));

async function withModules(run) {
  const vite = await createServer({
    root: webRoot,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    await run({
      contracts: await vite.ssrLoadModule("/src/a2ui/contracts.ts"),
      catalog: await vite.ssrLoadModule("/src/a2ui/catalog.tsx"),
      renderer: await vite.ssrLoadModule("/src/a2ui/renderer.tsx"),
    });
  } finally {
    await vite.close();
  }
}

test("strict A2UI contract accepts the audited complete intake envelope", async () => {
  await withModules(({ contracts }) => {
    const parsed = contracts.parseA2uiSurfaceEvent(intakeSurface());
    assert.equal(parsed.catalogId, "agentdesk.dev:intake-v1");
    assert.deepEqual(parsed.requiredFieldIds, ["workload_profile"]);
    assert.deepEqual(parsed.fields.map((field) => field.kind), ["single_select", "multi_select"]);
    assert.equal(
      contracts.isCurrentIntakeSurface(parsed, {
        sessionId: "session-1",
        status: "awaiting_input",
      }),
      true,
    );
    assert.equal(
      contracts.isCurrentIntakeSurface(parsed, {
        sessionId: "other-session",
        status: "awaiting_input",
      }),
      false,
    );
  });
});

for (const [name, mutate] of [
  ["unknown catalog", (value) => { value.catalogId = "untrusted:catalog"; }],
  ["unsupported protocol", (value) => { value.protocolVersion = "1.0"; }],
  ["unknown component", (value) => { value.messages[2].updateComponents.components[0].component = "Html"; }],
  ["active markup", (value) => { value.messages[2].updateComponents.components[0].text = "<img src=x onerror=alert(1)>"; }],
  ["URL-bearing text", (value) => { value.messages[2].updateComponents.components[0].text = "https://evil.example"; }],
  ["unknown action", (value) => { value.messages[2].updateComponents.components.at(-4).action.event.name = "run-code"; }],
  ["dynamic display binding", (value) => { value.messages[2].updateComponents.components[0].text = { path: "/secrets" }; }],
  ["unknown property", (value) => { value.messages[2].updateComponents.components[0].style = "display:none"; }],
  ["cross-session action", (value) => { value.messages[2].updateComponents.components.at(-4).action.event.context.sessionId = "other"; }],
  ["orphan component", (value) => { value.messages[2].updateComponents.components.push({ id: "orphan", component: "Text", text: "Unused", variant: "body" }); }],
  ["component cycle", (value) => { value.messages[2].updateComponents.components.at(-1).children = ["root"]; }],
  ["duplicate component ID", (value) => { value.messages[2].updateComponents.components[1].id = "intake-title"; }],
]) {
  test(`strict A2UI contract rejects ${name}`, async () => {
    await withModules(({ contracts }) => {
      const value = intakeSurface();
      mutate(value);
      assert.throws(() => contracts.parseA2uiSurfaceEvent(value), /A2UI|Invalid/u);
    });
  });
}

test("strict A2UI contract rejects an oversized surface before schema processing", async () => {
  await withModules(({ contracts }) => {
    const value = intakeSurface();
    value.padding = "x".repeat(129 * 1024);
    assert.throws(() => contracts.parseA2uiSurfaceEvent(value), /allowed size/u);
  });
});

test("trusted catalog is exact and official processor builds only the audited surface", async () => {
  await withModules(({ catalog, contracts, renderer }) => {
    assert.deepEqual(catalog.AGENTDESK_A2UI_COMPONENTS, [
      "Text",
      "TextField",
      "ChoicePicker",
      "CheckBox",
      "Column",
      "Row",
      "Button",
    ]);
    assert.deepEqual([...catalog.agentDeskA2uiCatalog.components.keys()], catalog.AGENTDESK_A2UI_COMPONENTS);
    const surface = contracts.parseA2uiSurfaceEvent(intakeSurface());
    const model = renderer.buildA2uiSurfaceModel(surface, () => {});
    assert.equal(model.catalog.id, surface.catalogId);
    assert.deepEqual(model.dataModel.get("/answers"), surface.answers);
    assert.equal(model.componentsModel.get("root").type, "Column");
  });
});

test("answer mapping validates required fields and converts single selection to text", async () => {
  await withModules(({ contracts, renderer }) => {
    const surface = contracts.parseA2uiSurfaceEvent(intakeSurface());
    const missing = renderer.normalizeIntakeAnswers(surface.fields, surface.answers);
    assert.deepEqual(missing.errors, { workload_profile: "Primary workload is required." });
    const valid = renderer.normalizeIntakeAnswers(surface.fields, {
      workload_profile: ["Transactional integrity"],
      operating_priorities: ["Data integrity"],
    });
    assert.deepEqual(valid.errors, {});
    assert.deepEqual(valid.answers, {
      workload_profile: "Transactional integrity",
      operating_priorities: ["Data integrity"],
    });
  });
});

test("local static fallback is accessible and preserves both bounded actions", async () => {
  await withModules(({ contracts, renderer }) => {
    const surface = contracts.parseA2uiSurfaceEvent(intakeSurface());
    const markup = renderToStaticMarkup(
      React.createElement(renderer.StaticIntakeForm, {
        surface,
        onSubmit() {},
        onSkip() {},
      }),
    );
    assert.match(markup, /data-renderer="static-fallback"/u);
    assert.match(markup, /<fieldset/u);
    assert.match(markup, />Continue</u);
    assert.match(markup, />Skip clarification</u);
  });
});

function intakeSurface() {
  const sessionId = "session-1";
  const proposalId = "proposal-1";
  const identity = { sessionId, proposalId, proposalVersion: "1.0" };
  const components = [
    { id: "intake-title", component: "Text", text: "Clarify your decision", variant: "h2" },
    { id: "intake-summary", component: "Text", text: "Clarify workload priorities before comparing databases.", variant: "body" },
    { id: "help-workload_profile", component: "Text", text: "Choose the primary production workload.", variant: "caption" },
    {
      id: "field-workload_profile",
      component: "ChoicePicker",
      label: "Primary workload",
      variant: "mutuallyExclusive",
      options: [
        { label: "Transactional integrity", value: "Transactional integrity" },
        { label: "Flexible documents", value: "Flexible documents" },
      ],
      value: { path: "/answers/workload_profile" },
      displayStyle: "checkbox",
      filterable: false,
      accessibility: { label: "Primary workload", description: "Choose the primary production workload." },
    },
    { id: "help-operating_priorities", component: "Text", text: "Select all priorities that matter.", variant: "caption" },
    {
      id: "field-operating_priorities",
      component: "ChoicePicker",
      label: "Operating priorities",
      variant: "multipleSelection",
      options: [
        { label: "Data integrity", value: "Data integrity" },
        { label: "Developer velocity", value: "Developer velocity" },
      ],
      value: { path: "/answers/operating_priorities" },
      displayStyle: "checkbox",
      filterable: false,
      accessibility: { label: "Operating priorities", description: "Select all priorities that matter." },
    },
    { id: "submit-label", component: "Text", text: "Continue", variant: "body" },
    { id: "skip-label", component: "Text", text: "Skip clarification", variant: "body" },
    {
      id: "submit-intake",
      component: "Button",
      child: "submit-label",
      variant: "primary",
      accessibility: { label: "Continue with these answers" },
      action: { event: { name: "agentdesk.intake.submit.v1", context: { ...identity, answers: { path: "/answers" } } } },
    },
    {
      id: "skip-intake",
      component: "Button",
      child: "skip-label",
      variant: "borderless",
      accessibility: { label: "Skip clarification" },
      action: { event: { name: "agentdesk.intake.skip.v1", context: identity } },
    },
    { id: "intake-actions", component: "Row", children: ["submit-intake", "skip-intake"], justify: "start", align: "center" },
    { id: "root", component: "Column", children: ["intake-title", "intake-summary", "help-workload_profile", "field-workload_profile", "help-operating_priorities", "field-operating_priorities", "intake-actions"], justify: "start", align: "stretch" },
  ];
  return {
    schemaVersion: "1.0",
    ...identity,
    surfaceId: "decision-intake",
    catalogId: "agentdesk.dev:intake-v1",
    catalogVersion: "1.0",
    protocolVersion: "0.9.1",
    wireVersion: "v0.9",
    messages: [
      { version: "v0.9", createSurface: { surfaceId: "decision-intake", catalogId: "agentdesk.dev:intake-v1", sendDataModel: false } },
      { version: "v0.9", updateDataModel: { surfaceId: "decision-intake", value: { answers: { workload_profile: [], operating_priorities: [] }, requiredFieldIds: ["workload_profile"], ...identity } } },
      { version: "v0.9", updateComponents: { surfaceId: "decision-intake", components } },
    ],
  };
}
