import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createServer } from "vite";

const webRoot = fileURLToPath(new URL("..", import.meta.url));
const fixtureUrl = new URL("../../../fixtures/agui/postgresql-vs-mongodb.golden.json", import.meta.url);

test("runtime mode is strict and demo input matches the shared golden fixture", async () => {
  const vite = await createServer({
    root: webRoot,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const {
      DEMO_RESEARCH_PARAMETERS,
      DEMO_RESEARCH_QUESTION,
      resolveRuntimeMode,
    } = await vite.ssrLoadModule("/src/app/runtime-mode.ts");
    const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));

    assert.equal(resolveRuntimeMode(undefined), "live");
    assert.equal(resolveRuntimeMode("live"), "live");
    assert.equal(resolveRuntimeMode("demo"), "demo");
    assert.throws(() => resolveRuntimeMode("fixture"), /must be live or demo/u);
    assert.equal(DEMO_RESEARCH_QUESTION, fixture.action.payload.question);
    assert.deepEqual(DEMO_RESEARCH_PARAMETERS, {
      options: fixture.action.payload.options,
      constraints: fixture.action.payload.constraints,
      criteria: fixture.action.payload.criteria,
      desiredDepth: fixture.action.payload.desiredDepth,
    });
  } finally {
    await vite.close();
  }
});
