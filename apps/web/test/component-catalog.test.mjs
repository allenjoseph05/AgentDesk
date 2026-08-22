import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createServer } from "vite";

const webRoot = fileURLToPath(new URL("..", import.meta.url));

test("trusted component catalog has an explicit version and exact allowlist", async () => {
  const vite = await createServer({
    root: webRoot,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const catalog = await vite.ssrLoadModule("/src/components/catalog.ts");

    assert.equal(catalog.AGENTDESK_COMPONENT_CATALOG_VERSION, "1.0");
    assert.deepEqual(Object.keys(catalog.agentDeskComponentCatalog).sort(), [
      "ActionControls",
      "ActivityTimeline",
      "ResearchResults",
      "ResearchStatusPanel",
      "SpecialistStatusList",
    ]);
    assert.equal(
      catalog.resolveCatalogComponent("ResearchResults"),
      catalog.agentDeskComponentCatalog.ResearchResults,
    );
    assert.throws(
      () => catalog.resolveCatalogComponent("ArbitraryHtml"),
      /Unknown AgentDesk component/u,
    );
    assert.throws(
      () => catalog.resolveCatalogComponent("toString"),
      /Unknown AgentDesk component/u,
    );
  } finally {
    await vite.close();
  }
});
