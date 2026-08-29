import assert from "node:assert/strict";
import test from "node:test";

import {
  createChallengeRecommendationAction,
  createFocusOnCriterionAction,
  createPrepareResearchAction,
  createResearchDeeperAction,
  createRetryFailedAgentAction,
  createSkipIntakeAction,
  createSubmitIntakeAction,
} from "../src/agui/actions.ts";
import {
  createBrowserCoordinatorAgent,
  createCoordinatorAgent,
  runAgentDeskAction,
  runResearch,
} from "../src/agui/client.ts";
import { INITIAL_AGENTDESK_STATE, parseAgentDeskViewState } from "../src/agui/state.ts";
import { AgentDeskStateStore } from "../src/agui/store.ts";
import { upsertTimelineItem } from "../src/agui/timeline.ts";

const encode = (event) => `data: ${JSON.stringify(event)}\n\n`;

test("official HttpAgent consumes lifecycle, state, and text events", async () => {
  let request;
  const mockFetch = async (_url, init) => {
    request = JSON.parse(init.body);
    const messageId = "assistant-1";
    return new Response(
      [
        { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
        {
          type: "STATE_SNAPSHOT",
          snapshot: {
            schemaVersion: "1.0",
            sessionId: request.runId,
            question: "PostgreSQL or MongoDB?",
            status: "planning",
            activeStep: "accept-research-request",
            agents: [],
            evidence: [],
            evidenceCount: 0,
            claims: [],
            analysis: null,
            verification: null,
            warnings: [],
            errors: [],
            availableActions: [],
            lastUpdatedAt: "2026-08-17T12:00:00Z",
          },
        },
        {
          type: "STATE_DELTA",
          delta: [
            { op: "replace", path: "/status", value: "researching" },
            { op: "replace", path: "/activeStep", value: "research" },
            {
              op: "replace",
              path: "/lastUpdatedAt",
              value: "2026-08-17T12:00:01Z",
            },
          ],
        },
        { type: "TEXT_MESSAGE_START", messageId, role: "assistant" },
        { type: "TEXT_MESSAGE_CONTENT", messageId, delta: "Request accepted." },
        { type: "TEXT_MESSAGE_END", messageId },
        { type: "RUN_FINISHED", threadId: request.threadId, runId: request.runId },
      ]
        .map(encode)
        .join(""),
      { headers: { "content-type": "text/event-stream" } },
    );
  };
  const states = [];
  const messages = [];
  let finished = false;
  const agent = createCoordinatorAgent(mockFetch);

  await runResearch(agent, "  PostgreSQL or MongoDB?  ", {
    onState: (state) => states.push(state),
    onMessage: (message) => messages.push(message),
    onFinished: () => {
      finished = true;
    },
  });

  assert.equal(request.messages.at(-1).content, "PostgreSQL or MongoDB?");
  assert.equal(request.state.schemaVersion, "1.0");
  assert.equal(request.forwardedProps.agentdesk.type, "start_research");
  assert.equal(request.forwardedProps.agentdesk.payload.question, "PostgreSQL or MongoDB?");
  assert.ok(request.forwardedProps.agentdesk.actionId);
  assert.equal(states.at(-1).status, "researching");
  assert.equal(states.at(-1).activeStep, "research");
  assert.deepEqual(messages, ["Request accepted."]);
  assert.equal(finished, true);
});

test("state boundary rejects unsupported schemas and malformed counts", () => {
  assert.throws(
    () => parseAgentDeskViewState({ schemaVersion: "99", status: "idle" }),
    /Unsupported AG-UI state schema/,
  );
  assert.throws(
    () =>
      parseAgentDeskViewState({
        ...INITIAL_AGENTDESK_STATE,
        evidenceCount: -1,
      }),
    /evidenceCount/,
  );
});

test("adaptive-intake action builders preserve exact proposal identity", () => {
  const prepare = createPrepareResearchAction("  Which database?  ");
  assert.equal(prepare.type, "prepare_research");
  assert.equal(prepare.payload.question, "Which database?");
  const submit = createSubmitIntakeAction({
    schemaVersion: "1.0",
    sessionId: "session-intake",
    proposalId: "proposal-intake",
    proposalVersion: "1.0",
    answers: { workload: "Transactional" },
  });
  assert.equal(submit.type, "submit_intake");
  assert.equal(submit.sessionId, "session-intake");
  assert.equal(submit.payload.response.proposalId, "proposal-intake");
  assert.deepEqual(createSkipIntakeAction(" session-intake ").payload, {});
  assert.throws(
    () => createSubmitIntakeAction({
      schemaVersion: "1.0",
      sessionId: "session-intake",
      proposalId: "proposal-intake",
      proposalVersion: "1.0",
      answers: { workload: "" },
    }),
    /too_small|at least 1|Invalid/u,
  );
});

test("official HttpAgent forwards only the named A2UI custom event", async () => {
  const expectedSurface = { marker: "trusted-boundary-input" };
  const mockFetch = async (_url, init) => {
    const request = JSON.parse(init.body);
    return new Response(
      [
        { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
        { type: "CUSTOM", name: "unrelated.custom.event", value: { ignored: true } },
        { type: "CUSTOM", name: "agentdesk.a2ui.surface.v1", value: expectedSurface },
        { type: "RUN_FINISHED", threadId: request.threadId, runId: request.runId },
      ].map(encode).join(""),
      { headers: { "content-type": "text/event-stream" } },
    );
  };
  const values = [];
  await runResearch(createCoordinatorAgent(mockFetch), "Which database?", {
    onA2uiSurface: (value) => {
      values.push(value);
      return true;
    },
  });
  assert.deepEqual(values, [expectedSurface]);
});

test("abortRun cancels the HTTP fetch and reports the SDK-suppressed abort", async () => {
  let requestSignal;
  let notifyFetchStarted;
  const fetchStarted = new Promise((resolve) => {
    notifyFetchStarted = resolve;
  });
  const mockFetch = async (_url, init) => {
    requestSignal = init.signal;
    notifyFetchStarted();
    return await new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => {
        reject(new DOMException("Fetch is aborted", "AbortError"));
      });
    });
  };
  const agent = createCoordinatorAgent(mockFetch);
  let cancelled = 0;
  let terminalCallbacks = 0;

  const running = runResearch(agent, "PostgreSQL or MongoDB?", {
    onCancelled: () => {
      cancelled += 1;
    },
    onFinished: () => {
      terminalCallbacks += 1;
    },
    onError: () => {
      terminalCallbacks += 1;
    },
  });
  await fetchStarted;
  agent.abortRun();
  await running;

  assert.equal(requestSignal.aborted, true);
  assert.equal(cancelled, 1);
  assert.equal(terminalCallbacks, 0);
  assert.equal(agent.isRunning, false);
});

test("reconnect preserves the thread, creates a new run, and applies a fresh snapshot", async () => {
  const requests = [];
  const states = [];
  const mockFetch = async (_url, init) => {
    const request = JSON.parse(init.body);
    requests.push(request);
    return new Response(
      [
        { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
        {
          type: "STATE_SNAPSHOT",
          snapshot: {
            ...INITIAL_AGENTDESK_STATE,
            sessionId: request.runId,
            question: request.messages.at(-1).content,
            status: "planning",
            activeStep: "accept-research-request",
            lastUpdatedAt: "2026-08-17T12:00:00Z",
          },
        },
        { type: "RUN_FINISHED", threadId: request.threadId, runId: request.runId },
      ]
        .map(encode)
        .join(""),
      { headers: { "content-type": "text/event-stream" } },
    );
  };

  const firstAgent = createCoordinatorAgent(mockFetch);
  await runResearch(firstAgent, "First connection", { onState: (state) => states.push(state) });
  const reconnectedAgent = createCoordinatorAgent(mockFetch, firstAgent.threadId);
  await runResearch(reconnectedAgent, "Reconnected", { onState: (state) => states.push(state) });

  assert.equal(requests[0].threadId, requests[1].threadId);
  assert.notEqual(requests[0].runId, requests[1].runId);
  assert.equal(states.at(-1).sessionId, requests[1].runId);
  assert.equal(states.at(-1).question, "Reconnected");
});

test("store rejection stops a malformed delta before the HttpAgent applies it", async () => {
  const snapshot = {
    ...INITIAL_AGENTDESK_STATE,
    sessionId: "session-safe",
    question: "Keep the last valid state?",
    status: "planning",
    activeStep: "plan",
    lastUpdatedAt: "2026-08-20T12:00:00Z",
  };
  const mockFetch = async (_url, init) => {
    const request = JSON.parse(init.body);
    return new Response(
      [
        { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
        { type: "STATE_SNAPSHOT", snapshot },
        {
          type: "STATE_DELTA",
          delta: [{ op: "replace", path: "/evidenceCount", value: 7 }],
        },
        { type: "RUN_FINISHED", threadId: request.threadId, runId: request.runId },
      ]
        .map(encode)
        .join(""),
      { headers: { "content-type": "text/event-stream" } },
    );
  };
  const store = new AgentDeskStateStore();
  const recoveryRequests = [];
  const states = [];
  store.subscribeRehydration((request) => recoveryRequests.push(request));
  const agent = createCoordinatorAgent(mockFetch);

  await runResearch(agent, snapshot.question, {
    onSnapshot: store.replaceSnapshot,
    onDelta: store.applyDelta,
    onState: (state) => states.push(state),
  });

  assert.deepEqual(store.getSnapshot(), snapshot);
  assert.deepEqual(agent.state, snapshot);
  assert.equal(states.length, 1);
  assert.equal(recoveryRequests.length, 1);
  assert.equal(recoveryRequests[0].cause, "delta");
});

test("typed follow-up actions use one thread and validated idempotency envelopes", async () => {
  const requests = [];
  const mockFetch = async (_url, init) => {
    const request = JSON.parse(init.body);
    requests.push(request);
    return new Response(
      [
        { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
        { type: "RUN_FINISHED", threadId: request.threadId, runId: request.runId },
      ].map(encode).join(""),
      { headers: { "content-type": "text/event-stream" } },
    );
  };
  const agent = createCoordinatorAgent(mockFetch, "thread-follow-up");
  const cases = [
    [createChallengeRecommendationAction("session-1", null), "Challenge recommendation."],
    [createResearchDeeperAction("session-1", ["Cost"]), "Research Cost more deeply."],
    [createFocusOnCriterionAction("session-1", "Cost"), "Focus on Cost."],
    [createRetryFailedAgentAction("session-1", "research-agent", "task-1"), "Retry research."],
  ];

  for (const [action, message] of cases) {
    await runAgentDeskAction(agent, action, message);
  }

  assert.equal(requests.length, 4);
  assert.ok(requests.every((request) => request.threadId === "thread-follow-up"));
  assert.deepEqual(requests.map((request) => request.forwardedProps.agentdesk.type), [
    "challenge_recommendation",
    "research_deeper",
    "focus_on_criterion",
    "retry_failed_agent",
  ]);
  assert.equal(
    new Set(requests.map((request) => request.forwardedProps.agentdesk.actionId)).size,
    requests.length,
  );
  assert.deepEqual(requests.at(-1).forwardedProps.agentdesk.payload, {
    agentId: "research-agent",
    remoteTaskId: "task-1",
  });
});

test("invalid action payload is rejected before messages or network work", async () => {
  let fetchCount = 0;
  const agent = createCoordinatorAgent(async () => {
    fetchCount += 1;
    throw new Error("fetch must not run");
  });

  await assert.rejects(
    runAgentDeskAction(
      agent,
      {
        schemaVersion: "1.0",
        actionId: "invalid-action",
        type: "focus_on_criterion",
        sessionId: "session-1",
        payload: { criterion: "" },
      },
      "Invalid focus.",
    ),
    /Invalid AgentDesk action/u,
  );
  assert.equal(fetchCount, 0);
  assert.equal(agent.messages.length, 0);
});

test("progressive text, steps, and specialist activity correlate without exposing reasoning", async () => {
  const mockFetch = async (_url, init) => {
    const request = JSON.parse(init.body);
    return new Response(
      [
        { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
        { type: "STEP_STARTED", stepName: "research-evidence" },
        { type: "TEXT_MESSAGE_START", messageId: "assistant-progress", role: "assistant" },
        { type: "TEXT_MESSAGE_CONTENT", messageId: "assistant-progress", delta: "Evidence " },
        { type: "TEXT_MESSAGE_CONTENT", messageId: "assistant-progress", delta: "accepted." },
        { type: "TEXT_MESSAGE_END", messageId: "assistant-progress" },
        {
          type: "ACTIVITY_SNAPSHOT",
          messageId: "research-progress",
          activityType: "specialist_progress",
          content: {
            agentId: "research-agent",
            summary: "One source accepted.",
            status: "working",
          },
          replace: true,
        },
        {
          type: "ACTIVITY_DELTA",
          messageId: "research-progress",
          activityType: "specialist_progress",
          patch: [
            { op: "replace", path: "/summary", value: "Two sources accepted." },
            { op: "replace", path: "/status", value: "completed" },
          ],
        },
        { type: "REASONING_START", messageId: "private-reasoning" },
        { type: "REASONING_MESSAGE_START", messageId: "private-reasoning", role: "reasoning" },
        {
          type: "REASONING_MESSAGE_CONTENT",
          messageId: "private-reasoning",
          delta: "PRIVATE CHAIN OF THOUGHT",
        },
        { type: "REASONING_MESSAGE_END", messageId: "private-reasoning" },
        { type: "REASONING_END", messageId: "private-reasoning" },
        { type: "STEP_FINISHED", stepName: "research-evidence" },
        { type: "RUN_FINISHED", threadId: request.threadId, runId: request.runId },
      ].map(encode).join(""),
      { headers: { "content-type": "text/event-stream" } },
    );
  };
  const updates = [];
  const messages = [];
  const agent = createCoordinatorAgent(mockFetch, "thread-timeline");

  await runResearch(agent, "Trace this run", {
    onMessage: (message) => messages.push(message),
    onTimelineItem: (item) => updates.push(item),
  });

  const timeline = updates.reduce(upsertTimelineItem, []);
  assert.deepEqual(messages, ["Evidence ", "Evidence accepted."]);
  assert.equal(timeline.find((item) => item.kind === "message").content, "Evidence accepted.");
  assert.equal(timeline.find((item) => item.kind === "message").status, "complete");
  assert.equal(timeline.find((item) => item.kind === "step").status, "complete");
  assert.equal(timeline.find((item) => item.kind === "activity").agentId, "research-agent");
  assert.equal(timeline.find((item) => item.kind === "activity").summary, "Two sources accepted.");
  assert.equal(timeline.find((item) => item.kind === "activity").status, "completed");
  assert.ok(timeline.every((item) => item.runId));
  assert.doesNotMatch(JSON.stringify(timeline), /PRIVATE CHAIN OF THOUGHT/u);
});

test("production browser client applies endpoint/auth config and keeps thread with new run ids", async () => {
  const stored = new Map();
  const storage = {
    getItem: (key) => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
  };
  const requests = [];
  let authCalls = 0;
  const mockFetch = async (url, init) => {
    const request = JSON.parse(init.body);
    requests.push({
      authorization: new Headers(init.headers).get("authorization"),
      request,
      url,
    });
    return new Response(
      [
        { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
        { type: "RUN_FINISHED", threadId: request.threadId, runId: request.runId },
      ].map(encode).join(""),
      { headers: { "content-type": "text/event-stream" } },
    );
  };
  const options = {
    environment: { VITE_AGENTDESK_AG_UI_ENDPOINT: "https://coordinator.example/ag-ui" },
    fetch: mockFetch,
    getAuthenticationHeaders: () => ({ Authorization: `Bearer auth-${++authCalls}` }),
    storage,
  };
  const identities = [];
  const firstAgent = createBrowserCoordinatorAgent(options);
  const first = await runResearch(firstAgent, "First browser run", {
    onRunIdentity: (identity) => identities.push(identity),
  });
  const second = await runResearch(firstAgent, "Second browser run", {
    onRunIdentity: (identity) => identities.push(identity),
  });
  const reconstructedAgent = createBrowserCoordinatorAgent(options);
  const third = await runResearch(reconstructedAgent, "Run after reconstruction", {
    onRunIdentity: (identity) => identities.push(identity),
  });

  assert.equal(requests.length, 3);
  assert.ok(requests.every(({ url }) => url === "https://coordinator.example/ag-ui"));
  assert.deepEqual(requests.map(({ authorization }) => authorization), [
    "Bearer auth-1",
    "Bearer auth-2",
    "Bearer auth-3",
  ]);
  assert.equal(first.threadId, second.threadId);
  assert.equal(second.threadId, third.threadId);
  assert.equal(reconstructedAgent.threadId, firstAgent.threadId);
  assert.equal(new Set([first.runId, second.runId, third.runId]).size, 3);
  assert.deepEqual(identities, [first, second, third]);
  assert.deepEqual(requests.map(({ request }) => request.runId), [
    first.runId,
    second.runId,
    third.runId,
  ]);
});

test("stream errors are mapped before reaching browser observers", async () => {
  const mockFetch = async (_url, init) => {
    const request = JSON.parse(init.body);
    return new Response(
      [
        { type: "RUN_STARTED", threadId: request.threadId, runId: request.runId },
        {
          type: "RUN_ERROR",
          message: "provider token sk-secret caused internal stack failure",
          code: "provider_failure",
        },
      ].map(encode).join(""),
      { headers: { "content-type": "text/event-stream" } },
    );
  };
  const errors = [];

  await runResearch(createCoordinatorAgent(mockFetch), "Map error", {
    onError: (message) => errors.push(message),
  });

  assert.deepEqual(errors, [
    "The Coordinator could not complete this run. Retry or start a new research session.",
  ]);
});
