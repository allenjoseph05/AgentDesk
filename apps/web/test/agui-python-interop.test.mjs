import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createCoordinatorAgent, runResearch } from "../src/agui/client.ts";
import { AgentDeskStateStore } from "../src/agui/store.ts";

const fixtureRoot = new URL("../../../fixtures/agui/", import.meta.url);
const pythonStream = readFileSync(
  new URL("official-python-stream.sse", fixtureRoot),
  "utf8",
).replaceAll("\r\n", "\n");
const malformedFixture = JSON.parse(
  readFileSync(new URL("malformed-events.json", fixtureRoot), "utf8"),
);
const encode = (event) => `data: ${JSON.stringify(event)}\n\n`;

const response = (stream) =>
  new Response(stream, { headers: { "content-type": "text/event-stream" } });

test("official JavaScript HttpAgent consumes the official Python SSE encoding", async () => {
  const store = new AgentDeskStateStore();
  const states = [];
  const messages = [];
  let finished = 0;
  const agent = createCoordinatorAgent(
    async () => response(pythonStream),
    "thread-python-contract",
  );

  await runResearch(agent, "PostgreSQL or MongoDB?", {
    onSnapshot: store.replaceSnapshot,
    onDelta: store.applyDelta,
    onState: (state) => states.push(state),
    onMessage: (message) => messages.push(message),
    onFinished: () => {
      finished += 1;
    },
  });

  assert.equal(finished, 1);
  assert.deepEqual(messages, ["Partial result retained."]);
  assert.equal(states.at(-1).status, "partial");
  assert.equal(states.at(-1).activeStep, null);
  assert.deepEqual(states.at(-1).warnings, ["Verifier unavailable; partial result retained."]);
  assert.deepEqual(store.getSnapshot(), states.at(-1));
  assert.deepEqual(agent.state, states.at(-1));
});

for (const fixtureCase of malformedFixture.cases) {
  test(`official JavaScript client fails closed: ${fixtureCase.caseId}`, async () => {
    const stream = fixtureCase.events.map(encode).join("");
    const agent = createCoordinatorAgent(
      async () => response(stream),
      `thread-${fixtureCase.caseId}`,
    );

    const originalConsoleError = console.error;
    console.error = () => {};
    try {
      await assert.rejects(runResearch(agent, "Reject malformed stream"), {
        message: new RegExp(fixtureCase.error, "u"),
      });
    } finally {
      console.error = originalConsoleError;
    }
  });
}
