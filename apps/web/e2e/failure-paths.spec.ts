import { readFileSync } from "node:fs";

import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";

const fixtureRoot = new URL("../../../fixtures/agui/", import.meta.url);
const loadFixture = (name: string) =>
  JSON.parse(readFileSync(new URL(name, fixtureRoot), "utf8"));
const goldenFixture = loadFixture("postgresql-vs-mongodb.golden.json");
const failureFixture = loadFixture("postgresql-vs-mongodb.failure.json");
const QUESTION = goldenFixture.action.payload.question as string;

interface AgUiRequest {
  forwardedProps: { agentdesk: Record<string, unknown> };
  runId: string;
  state: Record<string, unknown>;
  threadId: string;
}

interface BrowserHarness {
  browserLog: string[];
  requests: AgUiRequest[];
}

function encode(events: Record<string, unknown>[]): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

function requestAt(requests: AgUiRequest[], index: number): AgUiRequest {
  const request = requests[index];
  if (request === undefined) {
    throw new Error(`Missing captured AG-UI request at index ${index}.`);
  }
  return request;
}

function goldenState(sessionId = "session-golden"): Record<string, unknown> {
  return {
    ...structuredClone(goldenFixture.state),
    sessionId,
    lastUpdatedAt: "2026-08-23T12:30:00Z",
  };
}

function planningState(sessionId: string): Record<string, unknown> {
  return {
    ...goldenState(sessionId),
    status: "planning",
    activeStep: "research",
    agents: [],
    evidence: [],
    evidenceCount: 0,
    claims: [],
    analysis: null,
    recommendationChallenge: null,
    verification: null,
    warnings: [],
    errors: [],
    availableActions: [],
  };
}

function analystTimeoutState(): Record<string, unknown> {
  return {
    ...goldenState("session-analyst-timeout"),
    status: "partial",
    activeStep: "decision-analysis",
    agents: [
      {
        ...goldenFixture.state.agents[0],
        status: "completed",
        message: "Two fixture sources accepted.",
      },
      {
        ...goldenFixture.state.agents[1],
        status: "failed",
        message: "Analysis timed out before a recommendation was produced.",
      },
      {
        ...goldenFixture.state.agents[2],
        status: "waiting",
        message: "Waiting for analysis before verification.",
      },
    ],
    analysis: null,
    verification: null,
    warnings: ["The Analyst timed out; accepted research evidence was preserved."],
    errors: [],
    availableActions: ["retry_failed_agent"],
    lastUpdatedAt: "2026-08-23T12:31:00Z",
  };
}

function stateEvents(
  request: AgUiRequest,
  state: Record<string, unknown>,
  stepName: string,
): Record<string, unknown>[] {
  return [
    { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
    { type: "STEP_STARTED", stepName },
    { type: "STATE_SNAPSHOT", snapshot: state },
    { type: "STEP_FINISHED", stepName },
    {
      type: "RUN_FINISHED",
      threadId: request.threadId,
      runId: request.runId,
      result: { status: state.status },
    },
  ];
}

async function fulfillEvents(
  route: Route,
  events: Record<string, unknown>[],
): Promise<void> {
  await route.fulfill({
    body: encode(events),
    contentType: "text/event-stream",
    headers: { "cache-control": "no-store" },
    status: 200,
  });
}

function createHarness(page: Page): BrowserHarness {
  const harness: BrowserHarness = { browserLog: [], requests: [] };
  page.on("console", (message) =>
    harness.browserLog.push(`console:${message.type()}:${message.text()}`),
  );
  page.on("pageerror", (error) => harness.browserLog.push(`pageerror:${error.message}`));
  page.on("requestfailed", (request) =>
    harness.browserLog.push(
      `requestfailed:${request.method()}:${request.url()}:${request.failure()?.errorText}`,
    ),
  );
  return harness;
}

async function attachDiagnostics(testInfo: TestInfo, harness: BrowserHarness): Promise<void> {
  await testInfo.attach("failure-path-browser-and-agui-log", {
    body: Buffer.from(
      JSON.stringify(
        {
          browserLog: harness.browserLog,
          actions: harness.requests.map((request) => request.forwardedProps.agentdesk),
          runIds: harness.requests.map((request) => request.runId),
          threadIds: harness.requests.map((request) => request.threadId),
        },
        null,
        2,
      ),
    ),
    contentType: "application/json",
  });
}

async function openWorkspace(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What should we investigate?" })).toBeVisible();
}

async function submitResearch(page: Page): Promise<void> {
  await page.getByRole("textbox", { name: "Research question", exact: true }).fill(QUESTION);
  await page.getByRole("button", { name: "Start research" }).click();
}

async function expectGoldenRecovery(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "PostgreSQL", exact: true })).toBeVisible();
  await expect(page.getByText("PostgreSQL integrity fixture", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verification" })).toBeVisible();
}

test("Research Agent unavailable exposes a targeted retry that recovers", async ({ page }, testInfo) => {
  const harness = createHarness(page);
  await page.route("**/ag-ui", async (route) => {
    const request = route.request().postDataJSON() as AgUiRequest;
    harness.requests.push(request);
    const actionType = request.forwardedProps.agentdesk.type;
    const state =
      actionType === "retry_failed_agent"
        ? goldenState("session-failure")
        : structuredClone(failureFixture.state);
    await fulfillEvents(route, stateEvents(request, state, "research"));
  });

  try {
    await openWorkspace(page);
    await submitResearch(page);

    await expect(
      page
        .getByLabel("Coordinated agents")
        .getByText("The source provider is unavailable.", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await expectGoldenRecovery(page);

    expect(harness.requests).toHaveLength(2);
    expect(requestAt(harness.requests, 1).forwardedProps.agentdesk).toMatchObject({
      type: "retry_failed_agent",
      sessionId: "session-failure",
      payload: {
        agentId: "research-agent",
        remoteTaskId: "research-task-failure",
      },
    });
  } finally {
    await attachDiagnostics(testInfo, harness);
  }
});

test("Analyst timeout preserves evidence and recovers through targeted retry", async ({
  page,
}, testInfo) => {
  const harness = createHarness(page);
  await page.route("**/ag-ui", async (route) => {
    const request = route.request().postDataJSON() as AgUiRequest;
    harness.requests.push(request);
    const actionType = request.forwardedProps.agentdesk.type;
    const state =
      actionType === "retry_failed_agent"
        ? goldenState("session-analyst-timeout")
        : analystTimeoutState();
    await fulfillEvents(route, stateEvents(request, state, "decision-analysis"));
  });

  try {
    await openWorkspace(page);
    await submitResearch(page);

    await expect(page.getByText("PostgreSQL integrity fixture", { exact: true })).toBeVisible();
    await expect(
      page
        .getByLabel("Coordinated agents")
        .getByText("Analysis timed out before a recommendation was produced.", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("The Analyst timed out; accepted research evidence was preserved."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await expectGoldenRecovery(page);

    expect(harness.requests).toHaveLength(2);
    expect(requestAt(harness.requests, 1).forwardedProps.agentdesk).toMatchObject({
      type: "retry_failed_agent",
      sessionId: "session-analyst-timeout",
      payload: { agentId: "analyst-agent", remoteTaskId: "analysis-task-1" },
    });
  } finally {
    await attachDiagnostics(testInfo, harness);
  }
});

test("malformed AG-UI state fails closed and Try again rehydrates", async ({ page }, testInfo) => {
  const harness = createHarness(page);
  await page.route("**/ag-ui", async (route) => {
    const request = route.request().postDataJSON() as AgUiRequest;
    harness.requests.push(request);
    const state =
      harness.requests.length === 1
        ? { ...planningState("session-malformed-state"), schemaVersion: "99" }
        : goldenState("session-malformed-state");
    await fulfillEvents(route, stateEvents(request, state, "research"));
  });

  try {
    await openWorkspace(page);
    await submitResearch(page);

    const alert = page.getByRole("alert");
    await expect(alert).toContainText("A malformed AG-UI snapshot was rejected.");
    await expect(alert).toContainText("Unsupported AG-UI state schema: 99");
    await page.getByRole("button", { name: "Try again" }).click();
    await expectGoldenRecovery(page);
    expect(harness.requests).toHaveLength(2);
  } finally {
    await attachDiagnostics(testInfo, harness);
  }
});

test("malformed artifact patch preserves state and Try again recovers", async ({
  page,
}, testInfo) => {
  const harness = createHarness(page);
  await page.route("**/ag-ui", async (route) => {
    const request = route.request().postDataJSON() as AgUiRequest;
    harness.requests.push(request);
    if (harness.requests.length > 1) {
      await fulfillEvents(
        route,
        stateEvents(request, goldenState("session-malformed-artifact"), "research"),
      );
      return;
    }
    const events = [
      { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
      { type: "STEP_STARTED", stepName: "research" },
      { type: "STATE_SNAPSHOT", snapshot: planningState("session-malformed-artifact") },
      {
        type: "STATE_DELTA",
        delta: [{ op: "replace", path: "/evidenceCount", value: 1 }],
      },
      { type: "STEP_FINISHED", stepName: "research" },
      { type: "RUN_FINISHED", threadId: request.threadId, runId: request.runId },
    ];
    await fulfillEvents(route, events);
  });

  try {
    await openWorkspace(page);
    await submitResearch(page);

    const alert = page.getByRole("alert");
    await expect(alert).toContainText("A malformed AG-UI delta was rejected.");
    await expect(alert).toContainText("evidenceCount must equal the number of evidence items");
    await expect(page.getByText("No result artifacts yet")).toBeVisible();
    await page.getByRole("button", { name: "Try again" }).click();
    await expectGoldenRecovery(page);
    expect(harness.requests).toHaveLength(2);
  } finally {
    await attachDiagnostics(testInfo, harness);
  }
});

test("malformed action is rejected in the browser before network work", async ({
  page,
}, testInfo) => {
  const harness = createHarness(page);
  try {
    await openWorkspace(page);
    const result = await page.evaluate(async () => {
      const modulePath = "/src/agui/client.ts";
      const client = await import(modulePath);
      let fetchCalls = 0;
      const agent = client.createCoordinatorAgent(async () => {
        fetchCalls += 1;
        throw new Error("Network must not run for a malformed action.");
      });
      try {
        await client.runAgentDeskAction(
          agent,
          {
            schemaVersion: "1.0",
            actionId: "malformed-browser-action",
            type: "focus_on_criterion",
            sessionId: "session-browser-contract",
            payload: { criterion: "" },
          },
          "Focus on an invalid criterion.",
        );
        return { fetchCalls, message: null, rejected: false };
      } catch (error) {
        return {
          fetchCalls,
          message: error instanceof Error ? error.message : String(error),
          rejected: true,
        };
      }
    });

    expect(result).toMatchObject({ fetchCalls: 0, rejected: true });
    expect(result.message).toMatch(/Invalid AgentDesk action/u);
  } finally {
    await attachDiagnostics(testInfo, harness);
  }
});

test("broken AG-UI stream shows a safe error and succeeds on retry", async ({
  page,
}, testInfo) => {
  const harness = createHarness(page);
  await page.route("**/ag-ui", async (route) => {
    const request = route.request().postDataJSON() as AgUiRequest;
    harness.requests.push(request);
    if (harness.requests.length > 1) {
      await fulfillEvents(route, stateEvents(request, goldenState("session-stream-retry"), "research"));
      return;
    }
    await route.fulfill({
      body: `data: ${JSON.stringify({
        type: "RUN_STARTED",
        threadId: request.threadId,
        runId: request.runId,
      })}\n\ndata: {"type":`,
      contentType: "text/event-stream",
      status: 200,
    });
  });

  try {
    await openWorkspace(page);
    await submitResearch(page);

    const alert = page.getByRole("alert");
    await expect(alert).toContainText("Research connection failed");
    await expect(alert).toContainText(
      "The Coordinator could not complete this run. Retry or start a new research session.",
    );
    await page.getByRole("button", { name: "Try again" }).click();
    await expectGoldenRecovery(page);
    expect(harness.requests).toHaveLength(2);
  } finally {
    await attachDiagnostics(testInfo, harness);
  }
});

test("cancellation releases the UI and a fresh run succeeds", async ({ page }, testInfo) => {
  const harness = createHarness(page);
  let releaseCancellation!: () => void;
  const cancellationGate = new Promise<void>((resolve) => {
    releaseCancellation = resolve;
  });
  await page.route("**/ag-ui", async (route) => {
    const request = route.request().postDataJSON() as AgUiRequest;
    harness.requests.push(request);
    if (harness.requests.length > 1) {
      await fulfillEvents(route, stateEvents(request, goldenState("session-after-cancel"), "research"));
      return;
    }
    await cancellationGate;
    await route.abort("aborted").catch(() => undefined);
  });

  try {
    await openWorkspace(page);
    await submitResearch(page);

    await page.getByRole("button", { name: "Cancel active run" }).click();
    releaseCancellation();
    await expect(page.getByRole("button", { name: "Start research" })).toBeEnabled();
    await page.getByRole("button", { name: "Start research" }).click();
    await expectGoldenRecovery(page);

    expect(harness.requests).toHaveLength(2);
    expect(requestAt(harness.requests, 1).threadId).toBe(requestAt(harness.requests, 0).threadId);
    expect(requestAt(harness.requests, 1).runId).not.toBe(requestAt(harness.requests, 0).runId);
  } finally {
    releaseCancellation();
    await attachDiagnostics(testInfo, harness);
  }
});
