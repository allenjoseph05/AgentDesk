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
