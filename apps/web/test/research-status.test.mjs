import assert from "node:assert/strict";
import test from "node:test";

import {
  buildWorkflowStages,
  RESEARCH_STATUS_PRESENTATION,
  SPECIALIST_STATUS_PRESENTATION,
} from "../src/components/research-status.ts";

const researchStatuses = [
  "idle",
  "scoping",
  "awaiting_input",
  "planning",
  "researching",
  "analyzing",
  "verifying",
  "cancelling",
  "completed",
  "partial",
  "failed",
  "cancelled",
];

const specialistStatuses = [
  "pending",
  "working",
  "waiting",
  "completed",
  "failed",
  "cancelled",
];

test("every research and specialist state has explicit user-facing content", () => {
  assert.deepEqual(Object.keys(RESEARCH_STATUS_PRESENTATION), researchStatuses);
  assert.deepEqual(Object.keys(SPECIALIST_STATUS_PRESENTATION), specialistStatuses);

  for (const presentation of [
    ...Object.values(RESEARCH_STATUS_PRESENTATION),
    ...Object.values(SPECIALIST_STATUS_PRESENTATION),
  ]) {
    assert.ok(presentation.label.length > 0);
    assert.ok(presentation.description.length > 0);
    assert.doesNotMatch(`${presentation.label} ${presentation.description}`, /\d+%/u);
  }
});

test("workflow reports categorical stage states without fabricated progress", () => {
  assert.deepEqual(
    buildWorkflowStages("researching", "research").map(({ state }) => state),
    ["complete", "active", "queued", "queued"],
  );
  assert.deepEqual(
    buildWorkflowStages("partial", "verification").map(({ state }) => state),
    ["complete", "complete", "complete", "attention"],
  );
  assert.deepEqual(
    buildWorkflowStages("cancelling", "research").map(({ state }) => state),
    ["complete", "stopping", "queued", "queued"],
  );
  assert.ok(buildWorkflowStages("completed", "final-synthesis").every(
    ({ state }) => state === "complete",
  ));
});
