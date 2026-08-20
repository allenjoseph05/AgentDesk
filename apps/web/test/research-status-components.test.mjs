import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const webRoot = fileURLToPath(new URL("..", import.meta.url));

test("specialist cards render all bound statuses and messages accessibly", async () => {
  const vite = await createServer({
    root: webRoot,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const { SpecialistStatusList } = await vite.ssrLoadModule(
      "/src/components/SpecialistStatusList.tsx",
    );
    const statuses = ["pending", "working", "waiting", "completed", "failed", "cancelled"];
    const agents = statuses.map((status) => ({
      agentId: `agent-${status}`,
      name: `${status} specialist`,
      skill: "bound-status-test",
      status,
      remoteTaskId: null,
      message: `Observed ${status} state.`,
    }));

    const markup = renderToStaticMarkup(createElement(SpecialistStatusList, { agents }));

    for (const status of statuses) {
      assert.match(markup, new RegExp(`data-status="${status}"`, "u"));
      assert.match(markup, new RegExp(`Observed ${status} state`, "u"));
    }
    assert.match(markup, /aria-busy="true"/u);
    assert.doesNotMatch(markup, /role="progressbar"|\d+%/u);
  } finally {
    await vite.close();
  }
});

test("research panel binds partial workflow and waiting specialist state", async () => {
  const vite = await createServer({
    root: webRoot,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const { ResearchStatusPanel } = await vite.ssrLoadModule(
      "/src/components/ResearchStatusPanel.tsx",
    );
    const markup = renderToStaticMarkup(
      createElement(ResearchStatusPanel, {
        agents: [
          {
            agentId: "analyst",
            name: "Analyst Agent",
            skill: "decision-analysis",
            status: "waiting",
            remoteTaskId: null,
            message: "Waiting for sufficient evidence.",
          },
        ],
        evidenceCount: 1,
        isBusy: false,
        message: "Research stopped at a documented boundary.",
        onCancel: () => {},
        session: {
          activeStep: "verification",
          lastUpdatedAt: "2026-08-20T12:00:00Z",
          question: "Which database?",
          sessionId: "session-partial",
          status: "partial",
        },
      }),
    );

    assert.match(markup, /Partially complete/u);
    assert.match(markup, /Needs review/u);
    assert.match(markup, /Waiting for sufficient evidence/u);
    assert.match(markup, /observed states, not estimated percentage progress/u);
    assert.doesNotMatch(markup, /role="progressbar"|\d+%/u);
  } finally {
    await vite.close();
  }
});
