import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  selectActions,
  selectAgents,
  selectAnalysis,
  selectEvidence,
  selectSession,
  selectVerification,
  selectWarnings,
} from "../src/agui/selectors.ts";
import { AgentDeskStateStore } from "../src/agui/store.ts";

const fixture = JSON.parse(
  readFileSync(
    new URL("../../../fixtures/agui/postgresql-vs-mongodb.golden.json", import.meta.url),
    "utf8",
  ),
);

test("store atomically validates snapshot replacement and top-level deltas", () => {
  const store = new AgentDeskStateStore();
  let notifications = 0;
  store.subscribe(() => {
    notifications += 1;
  });

  assert.equal(store.replaceSnapshot(fixture.state), true);
  const snapshot = store.getSnapshot();
  assert.equal(Object.isFrozen(snapshot), true);
  assert.equal(Object.isFrozen(snapshot.evidence), true);
  assert.equal(
    store.applyDelta([
      { op: "replace", path: "/warnings", value: ["Awaiting final review."] },
    ]),
    true,
  );

  assert.notEqual(store.getSnapshot(), snapshot);
  assert.deepEqual(store.getSnapshot().warnings, ["Awaiting final review."]);
  assert.equal(notifications, 2);
});

test("malformed patches preserve the last valid state and request rehydration", () => {
  const store = new AgentDeskStateStore(fixture.state);
  const requests = [];
  store.subscribeRehydration((request) => requests.push(request));
  const lastValidState = store.getSnapshot();

  assert.equal(
    store.applyDelta([{ op: "replace", path: "/evidenceCount", value: 999 }]),
    false,
  );
  assert.equal(store.getSnapshot(), lastValidState);
  assert.equal(
    store.applyDelta([{ op: "replace", path: "/analysis/recommendation", value: "Unsafe" }]),
    false,
  );
  assert.equal(store.getSnapshot(), lastValidState);
  assert.equal(store.replaceSnapshot({ schemaVersion: "99" }), false);
  assert.equal(store.getSnapshot(), lastValidState);
  assert.equal(
    store.applyDelta([
      {
        op: "replace",
        path: "/warnings",
        value: ["x".repeat(128 * 1024)],
      },
    ]),
    false,
  );
  assert.equal(store.getSnapshot(), lastValidState);

  assert.deepEqual(
    requests.map(({ cause, sessionId }) => ({ cause, sessionId })),
    [
      { cause: "delta", sessionId: fixture.state.sessionId },
      { cause: "delta", sessionId: fixture.state.sessionId },
      { cause: "snapshot", sessionId: fixture.state.sessionId },
      { cause: "delta", sessionId: fixture.state.sessionId },
    ],
  );
});

test("domain selectors expose render-ready state without protocol parsing", () => {
  const state = new AgentDeskStateStore(fixture.state).getSnapshot();

  assert.deepEqual(selectSession(state), {
    activeStep: state.activeStep,
    lastUpdatedAt: state.lastUpdatedAt,
    question: state.question,
    sessionId: state.sessionId,
    status: state.status,
  });
  assert.equal(selectAgents(state), state.agents);
  assert.equal(selectEvidence(state), state.evidence);
  assert.equal(selectAnalysis(state), state.analysis);
  assert.equal(selectVerification(state), state.verification);
  assert.equal(selectWarnings(state), state.warnings);
  assert.equal(selectActions(state), state.availableActions);
});
