import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const webRoot = fileURLToPath(new URL("..", import.meta.url));
const fixtureRoot = new URL("../../../fixtures/agui/", import.meta.url);

async function fixtureState(name) {
  return JSON.parse(await readFile(new URL(name, fixtureRoot), "utf8")).state;
}

async function renderControls(props) {
  const vite = await createServer({
    root: webRoot,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const { ActionControls } = await vite.ssrLoadModule("/src/components/ActionControls.tsx");
    return renderToStaticMarkup(createElement(ActionControls, props));
  } finally {
    await vite.close();
  }
}

const handlers = {
  onCancel: () => {},
  onChallenge: async () => true,
  onFocusCriterion: async () => true,
  onResearchDeeper: async () => true,
  onRetryAgent: async () => true,
};

test("available follow-up controls render typed challenge, deeper, and criterion inputs", async () => {
  const state = await fixtureState("postgresql-vs-mongodb.golden.json");
  const markup = await renderControls({
    ...handlers,
    activeAction: null,
    agents: state.agents,
    analysis: state.analysis,
    availableActions: state.availableActions,
    isBusy: false,
  });

  assert.match(markup, /aria-busy="false"/u);
  assert.match(markup, /Challenge recommendation/u);
  assert.match(markup, /Test counterargument/u);
  assert.match(markup, /Deepen research/u);
  assert.match(markup, /Focus analysis/u);
  assert.match(markup, /value="Data integrity"/u);
  assert.doesNotMatch(markup, /Cancel active run/u);
});

test("retry control targets failed specialists and preserves remote task context", async () => {
  const state = await fixtureState("postgresql-vs-mongodb.failure.json");
  const markup = await renderControls({
    ...handlers,
    activeAction: null,
    agents: state.agents,
    analysis: state.analysis,
    availableActions: state.availableActions,
    isBusy: false,
  });

  assert.match(markup, /Retry a specialist/u);
  assert.match(markup, /Research Agent/u);
  assert.match(markup, /The source provider is unavailable/u);
  assert.match(markup, />Retry<\/button>/u);
});

test("busy state hides follow-up submissions and exposes only abort", async () => {
  const markup = await renderControls({
    ...handlers,
    activeAction: "research_deeper",
    agents: [],
    analysis: null,
    availableActions: ["research_deeper", "challenge_recommendation"],
    isBusy: true,
  });

  assert.match(markup, /aria-busy="true"/u);
  assert.match(markup, /Researching deeper/u);
  assert.match(markup, /Only one action can run at a time/u);
  assert.match(markup, /Cancel active run/u);
  assert.doesNotMatch(markup, /Test counterargument|Deepen research/u);
});
