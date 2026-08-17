import assert from "node:assert/strict";
import test from "node:test";

import { createCoordinatorAgent, runResearch } from "../src/agui/client.ts";
import { INITIAL_AGENTDESK_STATE, parseAgentDeskViewState } from "../src/agui/state.ts";

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
  assert.equal(states.at(-1).status, "planning");
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
