import assert from "node:assert/strict";
import test from "node:test";

import React from "react";

import { A2uiSurface } from "../src/a2ui/compatibility.ts";
import {
  createFixtureRuntime,
  processTrustedMessages,
  updateFixtureSummary,
} from "../src/a2ui/fixture-surface.ts";

test("creates a React A2UI surface from the local fixture", () => {
  const runtime = createFixtureRuntime();
  const element = React.createElement(A2uiSurface, { surface: runtime.surface });

  assert.equal(runtime.surface.id, "research-summary-spike");
  assert.equal(runtime.surface.componentsModel.get("root")?.type, "Card");
  assert.equal(runtime.surface.dataModel.get("/summary"), "Fixture surface ready.");
  assert.equal(element.type, A2uiSurface);

  runtime.processor.model.deleteSurface(runtime.surface.id);
});

test("updates data while retaining the same surface instance", () => {
  const runtime = createFixtureRuntime();
  const originalSurface = runtime.surface;

  updateFixtureSummary(runtime.processor, "Updated in place.");

  assert.equal(runtime.processor.model.getSurface(runtime.surface.id), originalSurface);
  assert.equal(originalSurface.dataModel.get("/summary"), "Updated in place.");

  runtime.processor.model.deleteSurface(runtime.surface.id);
});

test("rejects a component outside the trusted catalog", () => {
  const runtime = createFixtureRuntime();

  assert.throws(
    () =>
      processTrustedMessages(runtime.processor, [
        {
          version: "v0.9.1",
          updateComponents: {
            surfaceId: runtime.surface.id,
            components: [{ id: "unsafe", component: "ArbitraryHtml" }],
          },
        },
      ]),
    /Unknown A2UI component rejected: ArbitraryHtml/,
  );
  assert.equal(runtime.surface.componentsModel.get("unsafe"), undefined);

  runtime.processor.model.deleteSurface(runtime.surface.id);
});
