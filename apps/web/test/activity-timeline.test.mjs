import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const webRoot = fileURLToPath(new URL("..", import.meta.url));

test("timeline renders progressive messages and correlated semantic activity", async () => {
  const vite = await createServer({
    root: webRoot,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const { ActivityTimeline } = await vite.ssrLoadModule(
      "/src/components/ActivityTimeline.tsx",
    );
    const markup = renderToStaticMarkup(
      createElement(ActivityTimeline, {
        agents: [
          {
            agentId: "research-agent",
            name: "Research Agent",
            skill: "web-research",
            status: "working",
            remoteTaskId: "task-1",
            message: "Reviewing sources.",
          },
        ],
        items: [
          {
            id: "step:run-42:research",
            runId: "run-42",
            timestamp: null,
            kind: "step",
            label: "Research evidence",
            status: "active",
            stepName: "research",
          },
          {
            id: "message:run-42:assistant-1",
            runId: "run-42",
            timestamp: null,
            kind: "message",
            content: "Two sources accepted",
            role: "assistant",
            status: "streaming",
          },
          {
            id: "activity:run-42:activity-1",
            runId: "run-42",
            timestamp: null,
            kind: "activity",
            activityType: "source_review",
            agentId: "research-agent",
            status: "completed",
            summary: "Primary documentation accepted.",
          },
        ],
      }),
    );

    assert.match(markup, /aria-live="polite"/u);
    assert.match(markup, /data-run-id="run-42"/u);
    assert.match(markup, /data-agent-id="research-agent"/u);
    assert.match(markup, /Research Agent/u);
    assert.match(markup, /Two sources accepted/u);
    assert.match(markup, /Writing…/u);
    assert.match(markup, /Source review/u);
    assert.match(markup, /not private model reasoning/u);
    assert.doesNotMatch(markup, /chain.of.thought/iu);
  } finally {
    await vite.close();
  }
});
