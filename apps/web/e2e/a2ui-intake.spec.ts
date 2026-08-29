import { expect, test, type Route } from "@playwright/test";

import { installEmptyHistoryRoute } from "./history-route";

type AgUiRequest = {
  forwardedProps: { agentdesk: Record<string, unknown> };
  runId: string;
  threadId: string;
};

const encode = (events: Record<string, unknown>[]) =>
  events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");

async function fulfill(route: Route, events: Record<string, unknown>[]) {
  await route.fulfill({ body: encode(events), contentType: "text/event-stream", status: 200 });
}

test.beforeEach(async ({ page }) => {
  await installEmptyHistoryRoute(page);
});

test("live adaptive intake renders through the trusted A2UI catalog and blocks invalid input", async ({ page }) => {
  const requests: AgUiRequest[] = [];
  await page.route("**/ag-ui", async (route) => {
    const request = route.request().postDataJSON() as AgUiRequest;
    requests.push(request);
    const action = request.forwardedProps.agentdesk;
    if (action.type === "prepare_research") {
      await fulfill(route, [
        { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
        { type: "STATE_SNAPSHOT", snapshot: awaitingInputState() },
        { type: "CUSTOM", name: "agentdesk.a2ui.surface.v1", value: intakeSurface() },
        { type: "RUN_FINISHED", threadId: request.threadId, runId: request.runId, result: { status: "awaiting_input" } },
      ]);
      return;
    }
    await fulfill(route, [
      { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
      { type: "RUN_FINISHED", threadId: request.threadId, runId: request.runId, result: { status: "accepted" } },
    ]);
  });

  await page.goto("/");
  await page.getByRole("textbox", { name: "Research question", exact: true }).fill("Which database should we choose?");
  await page.getByRole("button", { name: "Start research" }).click();

  const intake = page.getByRole("region", { name: "Clarify research scope" });
  await expect(intake).toHaveAttribute("data-a2ui-catalog", "agentdesk.dev:intake-v1");
  await expect(intake.getByRole("textbox", { name: "Business constraint" })).toHaveAttribute("aria-required", "true");
  await intake.getByRole("button", { name: "Continue with these answers" }).click();
  await expect(intake.getByText("Business constraint is required.")).toBeVisible();
  expect(requests).toHaveLength(1);
  const prepareRequest = requests[0];
  if (prepareRequest === undefined) throw new Error("Expected the prepare AG-UI request.");
  expect(prepareRequest.forwardedProps.agentdesk.type).toBe("prepare_research");
});

test("a scoper failure exposes a trusted direct form and bypasses adaptive intake", async ({
  page,
}) => {
  const requests: AgUiRequest[] = [];
  await page.route("**/ag-ui", async (route) => {
    const request = route.request().postDataJSON() as AgUiRequest;
    requests.push(request);
    const action = request.forwardedProps.agentdesk;
    if (action.type === "prepare_research") {
      await fulfill(route, [
        { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
        {
          type: "STATE_SNAPSHOT",
          snapshot: {
            ...awaitingInputState(),
            status: "failed",
            activeStep: "decision-scoping",
            availableActions: [],
          },
        },
        {
          type: "RUN_ERROR",
          message: "Decision scoping failed; use the direct research form instead.",
          code: "decision_scoping_failed",
        },
      ]);
      return;
    }
    await fulfill(route, [
      { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
      {
        type: "RUN_FINISHED",
        threadId: request.threadId,
        runId: request.runId,
        result: { status: "accepted" },
      },
    ]);
  });

  await page.goto("/");
  await page
    .getByRole("textbox", { name: "Research question", exact: true })
    .fill("Which database should we choose?");
  await page.getByRole("button", { name: "Start research" }).click();
  await expect(page.getByRole("button", { name: "Use direct form" })).toBeVisible();
  await page.getByRole("button", { name: "Use direct form" }).click();
  await page.getByLabel("Options, separated by commas").fill("PostgreSQL, MongoDB");
  await page.getByLabel("Decision criteria, separated by commas").fill("Integrity, Flexibility");
  await page.getByLabel("Constraints, separated by commas").fill("Transactional workload");
  await page.getByRole("button", { name: "Start direct research" }).click();

  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]?.forwardedProps.agentdesk).toMatchObject({
    type: "start_research",
    payload: {
      options: ["PostgreSQL", "MongoDB"],
      constraints: ["Transactional workload"],
      criteria: ["Integrity", "Flexibility"],
    },
  });
});

function awaitingInputState() {
  return {
    schemaVersion: "1.0",
    sessionId: "session-intake",
    question: "Which database should we choose?",
    status: "awaiting_input",
    activeStep: "adaptive-intake",
    agents: [],
    evidence: [],
    evidenceCount: 0,
    claims: [],
    analysis: null,
    recommendationChallenge: null,
    verification: null,
    warnings: [],
    errors: [],
    availableActions: ["submit_intake", "skip_intake"],
    lastUpdatedAt: "2026-08-28T10:00:00Z",
  };
}

function intakeSurface() {
  const identity = { sessionId: "session-intake", proposalId: "proposal-intake", proposalVersion: "1.0" };
  const surfaceId = "decision-intake";
  const components = [
    { id: "intake-title", component: "Text", text: "Clarify your decision", variant: "h2" },
    { id: "intake-summary", component: "Text", text: "One constraint will improve the comparison.", variant: "body" },
    { id: "help-constraint", component: "Text", text: "Name the most important non-negotiable constraint.", variant: "caption" },
    { id: "field-constraint", component: "TextField", label: "Business constraint", value: { path: "/answers/constraint" }, variant: "shortText", accessibility: { label: "Business constraint", description: "Name the most important non-negotiable constraint." } },
    { id: "submit-label", component: "Text", text: "Continue", variant: "body" },
    { id: "skip-label", component: "Text", text: "Skip clarification", variant: "body" },
    { id: "submit-intake", component: "Button", child: "submit-label", variant: "primary", accessibility: { label: "Continue with these answers" }, action: { event: { name: "agentdesk.intake.submit.v1", context: { ...identity, answers: { path: "/answers" } } } } },
    { id: "skip-intake", component: "Button", child: "skip-label", variant: "borderless", accessibility: { label: "Skip clarification" }, action: { event: { name: "agentdesk.intake.skip.v1", context: identity } } },
    { id: "intake-actions", component: "Row", children: ["submit-intake", "skip-intake"], justify: "start", align: "center" },
    { id: "root", component: "Column", children: ["intake-title", "intake-summary", "help-constraint", "field-constraint", "intake-actions"], justify: "start", align: "stretch" },
  ];
  return {
    schemaVersion: "1.0",
    ...identity,
    surfaceId,
    catalogId: "agentdesk.dev:intake-v1",
    catalogVersion: "1.0",
    protocolVersion: "0.9.1",
    wireVersion: "v0.9",
    messages: [
      { version: "v0.9", createSurface: { surfaceId, catalogId: "agentdesk.dev:intake-v1", sendDataModel: false } },
      { version: "v0.9", updateDataModel: { surfaceId, value: { answers: { constraint: "" }, requiredFieldIds: ["constraint"], ...identity } } },
      { version: "v0.9", updateComponents: { surfaceId, components } },
    ],
  };
}
