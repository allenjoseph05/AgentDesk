import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const webRoot = fileURLToPath(new URL("..", import.meta.url));

test("application shell renders its landmarks with one thread-scoped agent", async () => {
  const vite = await createServer({
    root: webRoot,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const [{ AgentDeskRuntimeProvider }, { AgentDeskWorkspace }, { createCoordinatorAgent }] =
      await Promise.all([
        vite.ssrLoadModule("/src/app/AgentDeskRuntime.tsx"),
        vite.ssrLoadModule("/src/app/AgentDeskWorkspace.tsx"),
        vite.ssrLoadModule("/src/agui/client.ts"),
      ]);
    let agentCount = 0;
    const markup = renderToStaticMarkup(
      createElement(
        AgentDeskRuntimeProvider,
        {
          createAgent: () => {
            agentCount += 1;
            return createCoordinatorAgent(undefined, "thread-shell-test");
          },
        },
        createElement(AgentDeskWorkspace),
      ),
    );

    assert.equal(agentCount, 1);
    assert.match(markup, /<aside[^>]+aria-label="Research history"/);
    assert.match(markup, /<form[^>]+class="research-composer"/);
    assert.match(markup, /data-surface="agentdesk-state"/);
    assert.match(markup, /Thread ready/);
  } finally {
    await vite.close();
  }
});

test("loading fallback exposes a busy live region", async () => {
  const vite = await createServer({
    root: webRoot,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const { ShellLoadingFallback } = await vite.ssrLoadModule(
      "/src/app/boundaries.tsx",
    );
    const markup = renderToStaticMarkup(createElement(ShellLoadingFallback));

    assert.match(markup, /aria-busy="true"/);
    assert.match(markup, /aria-live="polite"/);
    assert.match(markup, /Preparing your research workspace/);
  } finally {
    await vite.close();
  }
});
