import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  ActionSubmissionGate,
  createChallengeRecommendationAction,
  createFocusOnCriterionAction,
  createResearchDeeperAction,
  createRetryFailedAgentAction,
  parseAgentDeskAction,
} from "../src/agui/actions.ts";
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

test("frontend state rejects values outside the Python domain contract", () => {
  const fixture = JSON.parse(
    readFileSync(new URL("postgresql-vs-mongodb.golden.json", fixtureRoot), "utf8"),
  );

  const invalidWeight = structuredClone(fixture.state);
  invalidWeight.analysis.criteria[0].weight = 2;
  assert.throws(() => parseAgentDeskViewState(invalidWeight), /Invalid AG-UI state/);

  const invalidScore = structuredClone(fixture.state);
  invalidScore.analysis.criteria[0].scores.PostgreSQL = 99;
  assert.throws(() => parseAgentDeskViewState(invalidScore), /Invalid AG-UI state/);

  const unsupportedClaim = structuredClone(fixture.state);
  unsupportedClaim.claims[0].evidenceIds = [];
  assert.throws(() => parseAgentDeskViewState(unsupportedClaim), /Invalid AG-UI state/);

  const incompleteAnalysis = structuredClone(fixture.state);
  incompleteAnalysis.analysis.argumentsFor = [];
  assert.throws(() => parseAgentDeskViewState(incompleteAnalysis), /Invalid AG-UI state/);

  const unsafeUrl = structuredClone(fixture.state);
  unsafeUrl.evidence[0].sourceUrl = "javascript:alert(1)";
  assert.throws(() => parseAgentDeskViewState(unsafeUrl), /HTTP or HTTPS/);

  const oversizedState = structuredClone(fixture.state);
  oversizedState.warnings = Array.from({ length: 17 }, () => "x".repeat(16 * 1024));
  assert.throws(() => parseAgentDeskViewState(oversizedState), /exceeds the allowed size/);
});

test("frontend payload defaults mirror Python contract defaults", () => {
  assert.deepEqual(
    parseAgentDeskAction({
      schemaVersion: "1.0",
      actionId: "action-defaults",
      type: "start_research",
      sessionId: null,
      payload: { question: "Which database?" },
    }).payload,
    {
      question: "Which database?",
      options: [],
      constraints: [],
      criteria: [],
      desiredDepth: "normal",
    },
  );
  assert.deepEqual(parseAgentDeskViewState({ schemaVersion: "1.0" }), {
    schemaVersion: "1.0",
    sessionId: null,
    question: null,
    status: "idle",
    activeStep: null,
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
    lastUpdatedAt: null,
  });
});

test("typed follow-up builders normalize and validate every action envelope", () => {
  const actions = [
    createChallengeRecommendationAction(" session-1 ", " Test the migration risk. "),
    createResearchDeeperAction(" session-1 ", [" Cost ", "Cost", "Operations"]),
    createFocusOnCriterionAction(" session-1 ", " Data integrity "),
    createRetryFailedAgentAction(" session-1 ", " research-agent ", " task-1 "),
  ];

  assert.deepEqual(actions.map((action) => action.type), [
    "challenge_recommendation",
    "research_deeper",
    "focus_on_criterion",
    "retry_failed_agent",
  ]);
  assert.ok(actions.every((action) => action.sessionId === "session-1"));
  assert.equal(new Set(actions.map((action) => action.actionId)).size, actions.length);
  assert.deepEqual(actions[1].payload.focusAreas, ["Cost", "Operations"]);
  assert.equal(actions[2].payload.criterion, "Data integrity");
  assert.throws(() => createFocusOnCriterionAction("session-1", "  "), /Invalid/);
});

test("submission gate rejects concurrent actions and releases only the active id", () => {
  const gate = new ActionSubmissionGate();

  assert.equal(gate.begin("action-1"), true);
  assert.equal(gate.activeActionId, "action-1");
  assert.equal(gate.begin("action-2"), false);
  gate.finish("action-2");
  assert.equal(gate.activeActionId, "action-1");
  gate.finish("action-1");
  assert.equal(gate.activeActionId, null);
  assert.equal(gate.begin("action-2"), true);
});
