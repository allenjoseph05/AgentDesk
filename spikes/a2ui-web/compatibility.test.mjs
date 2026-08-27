import assert from "node:assert/strict";
import test from "node:test";

import { A2uiSurface, basicCatalog } from "@a2ui/react/v0_9";
import { MessageProcessor, SurfaceModel } from "@a2ui/web_core/v0_9";

test("pinned A2UI v0.9 renderer entrypoints resolve with React 19", () => {
  assert.equal(typeof A2uiSurface, "function");
  assert.equal(typeof basicCatalog, "object");
  assert.equal(typeof MessageProcessor, "function");
  assert.equal(typeof SurfaceModel, "function");
});
