import assert from "node:assert/strict";
import test from "node:test";

import {
  createActivityTimelineItem,
  MAX_TIMELINE_ITEMS,
  semanticLabel,
  upsertTimelineItem,
} from "../src/agui/timeline.ts";

test("activity projection allowlists user-safe summary and specialist correlation", () => {
  const item = createActivityTimelineItem({
    activityType: "source_review",
    content: {
      agentId: "research-agent",
      summary: "  Source accepted.  ",
      status: "completed",
      chainOfThought: "must never be copied",
      arbitraryPayload: { secret: true },
    },
    messageId: "activity-1",
    runId: "run-1",
  });

  assert.deepEqual(item, {
    id: "activity:run-1:activity-1",
    runId: "run-1",
    timestamp: null,
    kind: "activity",
    activityType: "source_review",
    agentId: "research-agent",
    status: "completed",
    summary: "Source accepted.",
  });
  assert.equal(
    createActivityTimelineItem({
      activityType: "reasoning",
      content: { chainOfThought: "private" },
      messageId: "unsafe",
      runId: "run-1",
    }),
    null,
  );
  assert.equal(semanticLabel("source_review"), "Source review");
});

test("timeline updates in place and retains only a bounded recent history", () => {
  const first = {
    id: "message:run-1:message-1",
    runId: "run-1",
    timestamp: null,
    kind: "message",
    content: "First",
    role: "assistant",
    status: "streaming",
  };
  const completed = { ...first, content: "First complete", status: "complete" };
  assert.deepEqual(upsertTimelineItem([first], completed), [completed]);

  let timeline = [];
  for (let index = 0; index < MAX_TIMELINE_ITEMS + 7; index += 1) {
    timeline = upsertTimelineItem(timeline, {
      ...first,
      id: `message:run-1:${index}`,
      content: String(index),
    });
  }
  assert.equal(timeline.length, MAX_TIMELINE_ITEMS);
  assert.equal(timeline[0].content, "7");
});
