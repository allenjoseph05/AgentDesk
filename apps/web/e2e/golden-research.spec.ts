import { readFileSync } from "node:fs";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

const fixtureRoot = new URL("../../../fixtures/agui/", import.meta.url);
const goldenFixture = JSON.parse(
  readFileSync(new URL("postgresql-vs-mongodb.golden.json", fixtureRoot), "utf8"),
);
const QUESTION = goldenFixture.action.payload.question;
const CHALLENGE = "What if schema flexibility matters more than relational integrity?";

interface AgUiRequest {
  forwardedProps: { agentdesk: Record<string, unknown> };
  messages: Array<{ content: string; role: string }>;
  runId: string;
  state: Record<string, unknown>;
  threadId: string;
}

function requireRequest(requests: AgUiRequest[], index: number): AgUiRequest {
  const request = requests[index];
  if (request === undefined) {
    throw new Error(`Missing captured AG-UI request at index ${index}.`);
  }
  return request;
}

function encode(events: Record<string, unknown>[]): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

function initialResearchState(): Record<string, unknown> {
  return {
    ...goldenFixture.state,
    status: "planning",
    activeStep: "research-evidence",
    agents: goldenFixture.state.agents.map((agent: Record<string, unknown>, index: number) => ({
      ...agent,
      status: index === 0 ? "working" : "pending",
      remoteTaskId: index === 0 ? agent.remoteTaskId : null,
      message: index === 0 ? "Research Agent started fixture retrieval." : "Awaiting assignment.",
    })),
    evidence: [],
    evidenceCount: 0,
    claims: [],
    analysis: null,
    recommendationChallenge: null,
    verification: null,
    warnings: [],
    errors: [],
    availableActions: [],
    lastUpdatedAt: "2026-08-17T12:00:01Z",
  };
}

function finalStateDelta(): Record<string, unknown>[] {
  return Object.entries(goldenFixture.state)
    .filter(([key]) => !["schemaVersion", "sessionId", "question"].includes(key))
    .map(([key, value]) => ({ op: "replace", path: `/${key}`, value }));
}

function researchEvents(request: AgUiRequest): Record<string, unknown>[] {
  return [
    { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
    { type: "STEP_STARTED", stepName: "research-evidence" },
    { type: "STATE_SNAPSHOT", snapshot: initialResearchState() },
    {
      type: "ACTIVITY_SNAPSHOT",
      messageId: "research-golden-progress",
      activityType: "specialist_progress",
      content: {
        agentId: "research-agent",
        status: "working",
        summary: "Research Agent started fixture retrieval.",
      },
      replace: true,
    },
    { type: "STATE_DELTA", delta: finalStateDelta() },
    {
      type: "ACTIVITY_DELTA",
      messageId: "research-golden-progress",
      activityType: "specialist_progress",
      patch: [
        { op: "replace", path: "/status", value: "completed" },
        { op: "replace", path: "/summary", value: "Two fixture sources accepted." },
      ],
    },
    { type: "STEP_FINISHED", stepName: "research-evidence" },
    { type: "STEP_STARTED", stepName: "decision-analysis" },
    {
      type: "ACTIVITY_SNAPSHOT",
      messageId: "analyst-golden-progress",
      activityType: "specialist_progress",
      content: {
        agentId: "analyst-agent",
        status: "completed",
        summary: "Comparison complete.",
      },
      replace: true,
    },
    { type: "STEP_FINISHED", stepName: "decision-analysis" },
    { type: "TEXT_MESSAGE_START", messageId: "golden-result", role: "assistant" },
    {
      type: "TEXT_MESSAGE_CONTENT",
      messageId: "golden-result",
      delta: "Research, analysis, and verification complete.",
    },
    { type: "TEXT_MESSAGE_END", messageId: "golden-result" },
    {
      type: "RUN_FINISHED",
      threadId: request.threadId,
      runId: request.runId,
      result: { sessionId: goldenFixture.state.sessionId, status: "completed" },
    },
  ];
}

function challengedState(): Record<string, unknown> {
  return {
    ...goldenFixture.state,
    activeStep: "challenge-recommendation",
    recommendationChallenge: {
      currentRecommendation: "PostgreSQL",
      strongestAlternative: "MongoDB",
      strongestCounterargument:
        "MongoDB becomes the stronger choice when flexible document structures outweigh relational integrity.",
      supportingClaimIds: ["claim-mongo"],
      assumptions: ["Independent document writes become the dominant workload."],
      evidenceGaps: ["Production access patterns are not measured."],
      recommendationChangesIf: [
        "Schema flexibility becomes more important than relational integrity.",
      ],
    },
    lastUpdatedAt: "2026-08-17T12:00:20Z",
  };
}

function challengeEvents(request: AgUiRequest): Record<string, unknown>[] {
  return [
    { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
    { type: "STEP_STARTED", stepName: "challenge-recommendation" },
    { type: "STATE_SNAPSHOT", snapshot: challengedState() },
    { type: "TEXT_MESSAGE_START", messageId: "golden-challenge", role: "assistant" },
    {
      type: "TEXT_MESSAGE_CONTENT",
      messageId: "golden-challenge",
      delta: "The strongest counterargument is ready.",
    },
    { type: "TEXT_MESSAGE_END", messageId: "golden-challenge" },
    { type: "STEP_FINISHED", stepName: "challenge-recommendation" },
    {
      type: "RUN_FINISHED",
      threadId: request.threadId,
      runId: request.runId,
      result: { sessionId: goldenFixture.state.sessionId, status: "completed" },
    },
  ];
}

async function attachDiagnostics(
  testInfo: TestInfo,
  browserLog: string[],
  requests: AgUiRequest[],
): Promise<void> {
  await testInfo.attach("browser-and-agui-log", {
    body: Buffer.from(
      JSON.stringify(
        {
          browserLog,
          actions: requests.map((request) => request.forwardedProps.agentdesk),
          runIds: requests.map((request) => request.runId),
          threadIds: requests.map((request) => request.threadId),
        },
        null,
        2,
      ),
    ),
    contentType: "application/json",
  });
}

function monitorPage(page: Page, browserLog: string[]): void {
  page.on("console", (message) => browserLog.push(`console:${message.type()}:${message.text()}`));
  page.on("pageerror", (error) => browserLog.push(`pageerror:${error.message}`));
  page.on("requestfailed", (request) =>
    browserLog.push(`requestfailed:${request.method()}:${request.url()}:${request.failure()?.errorText}`),
  );
}

test("golden research renders AG-UI state and submits a typed challenge", async ({ page }, testInfo) => {
  const requests: AgUiRequest[] = [];
  const browserLog: string[] = [];
  monitorPage(page, browserLog);
  await page.route("**/ag-ui", async (route) => {
    const request = route.request().postDataJSON() as AgUiRequest;
    requests.push(request);
    const action = request.forwardedProps.agentdesk;
    const events =
      action.type === "start_research" ? researchEvents(request) : challengeEvents(request);
    await route.fulfill({
      body: encode(events),
      contentType: "text/event-stream",
      headers: { "cache-control": "no-store" },
      status: 200,
    });
  });

  try {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "What should we investigate?" })).toBeVisible();

    await page.getByRole("textbox", { name: "Research question", exact: true }).fill(QUESTION);
    await page.getByRole("button", { name: "Start research" }).click();

    await expect(page.getByRole("heading", { name: "PostgreSQL", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();
    await expect(page.getByText("PostgreSQL integrity fixture", { exact: true })).toBeVisible();
    await expect(page.getByText("Two fixture sources accepted.", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Comparison complete.", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Verification" })).toBeVisible();

    expect(requests).toHaveLength(1);
    const startRequest = requireRequest(requests, 0);
    expect(startRequest.forwardedProps.agentdesk).toMatchObject({
      schemaVersion: "1.0",
      type: "start_research",
      sessionId: null,
      payload: { question: QUESTION },
    });
    expect(startRequest.state).toMatchObject({ schemaVersion: "1.0", status: "idle" });

    await page.getByLabel("Optional challenge").fill(CHALLENGE);
    await page.getByRole("button", { name: "Test counterargument" }).click();

    await expect(
      page.getByRole("heading", { name: "Strongest alternative: MongoDB" }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "MongoDB becomes the stronger choice when flexible document structures outweigh relational integrity.",
      ),
    ).toBeVisible();

    expect(requests).toHaveLength(2);
    const challengeRequest = requireRequest(requests, 1);
    expect(challengeRequest.threadId).toBe(startRequest.threadId);
    expect(challengeRequest.runId).not.toBe(startRequest.runId);
    expect(challengeRequest.state).toMatchObject({
      schemaVersion: "1.0",
      sessionId: "session-golden",
      status: "completed",
      analysis: { recommendation: "PostgreSQL" },
    });
    expect(challengeRequest.forwardedProps.agentdesk).toMatchObject({
      schemaVersion: "1.0",
      type: "challenge_recommendation",
      sessionId: "session-golden",
      payload: { challenge: CHALLENGE },
    });
    expect(challengeRequest.messages.at(-1)).toMatchObject({
      role: "user",
      content: CHALLENGE,
    });
    expect(browserLog.filter((entry) => entry.startsWith("pageerror:"))).toEqual([]);
    expect(browserLog.filter((entry) => entry.startsWith("requestfailed:"))).toEqual([]);
  } finally {
    await attachDiagnostics(testInfo, browserLog, requests);
  }
});
