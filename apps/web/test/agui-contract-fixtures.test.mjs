import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseAgentDeskAction } from "../src/agui/actions.ts";
import { parseAgentDeskViewState } from "../src/agui/state.ts";

const fixtureRoot = new URL("../../../fixtures/agui/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("manifest.json", fixtureRoot), "utf8"));

for (const entry of manifest.fixtures) {
  test(`validates shared AG-UI fixture: ${entry.fixtureId}`, () => {
    const fixture = JSON.parse(readFileSync(new URL(entry.file, fixtureRoot), "utf8"));

    if (entry.valid) {
      assert.deepEqual(parseAgentDeskAction(fixture.action), fixture.action);
      assert.deepEqual(parseAgentDeskViewState(fixture.state), fixture.state);
      return;
    }

    assert.throws(() => parseAgentDeskAction(fixture.action), /Unsupported AG-UI action schema/);
    assert.throws(() => parseAgentDeskViewState(fixture.state), /Unsupported AG-UI state schema/);
  });
}

test("all follow-up action variants validate and require a session", () => {
  const variants = [
    ["challenge_recommendation", { challenge: null }],
    ["research_deeper", { focusAreas: ["Cost"], desiredDepth: "deep" }],
    ["focus_on_criterion", { criterion: "Cost" }],
    ["retry_failed_agent", { agentId: "research-agent", remoteTaskId: null }],
  ];

  for (const [type, payload] of variants) {
    const action = {
      schemaVersion: "1.0",
      actionId: `action-${type}`,
      type,
      sessionId: "session-1",
      payload,
    };
    assert.equal(parseAgentDeskAction(action).type, type);
    assert.throws(() => parseAgentDeskAction({ ...action, sessionId: null }), /Invalid/);
  }
});
