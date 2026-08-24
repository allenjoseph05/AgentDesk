import { z } from "zod";

export const AG_UI_ACTION_SCHEMA_VERSION = "1.0" as const;
export const MAX_AG_UI_FORWARDED_PROPS_BYTES = 32 * 1024;
const MAX_ACTION_TEXT_LENGTH = 16 * 1024;
const MAX_ACTION_LIST_LENGTH = 20;

const nonEmptyText = z.string().trim().min(1).max(MAX_ACTION_TEXT_LENGTH);
const startResearchPayloadSchema = z
  .object({
    question: nonEmptyText,
    options: z.array(nonEmptyText).max(MAX_ACTION_LIST_LENGTH).default([]),
    constraints: z.array(nonEmptyText).max(MAX_ACTION_LIST_LENGTH).default([]),
    criteria: z.array(nonEmptyText).max(MAX_ACTION_LIST_LENGTH).default([]),
    desiredDepth: z.enum(["fast", "normal", "deep"]).default("normal"),
  })
  .strict();

const common = {
  schemaVersion: z.literal(AG_UI_ACTION_SCHEMA_VERSION),
  actionId: nonEmptyText,
};

export const AgentDeskActionSchema = z.discriminatedUnion("type", [
  z
    .object({
      ...common,
      type: z.literal("start_research"),
      sessionId: z.null(),
      payload: startResearchPayloadSchema,
    })
    .strict(),
  z
    .object({
      ...common,
      type: z.literal("challenge_recommendation"),
      sessionId: nonEmptyText,
      payload: z.object({ challenge: nonEmptyText.nullable().default(null) }).strict(),
    })
    .strict(),
  z
    .object({
      ...common,
      type: z.literal("research_deeper"),
      sessionId: nonEmptyText,
      payload: z
        .object({
          focusAreas: z.array(nonEmptyText).max(MAX_ACTION_LIST_LENGTH).default([]),
          desiredDepth: z.enum(["normal", "deep"]).default("deep"),
        })
        .strict(),
    })
    .strict(),
  z
    .object({
      ...common,
      type: z.literal("focus_on_criterion"),
      sessionId: nonEmptyText,
      payload: z.object({ criterion: nonEmptyText }).strict(),
    })
    .strict(),
  z
    .object({
      ...common,
      type: z.literal("retry_failed_agent"),
      sessionId: nonEmptyText,
      payload: z
        .object({
          agentId: nonEmptyText,
          remoteTaskId: nonEmptyText.nullable().default(null),
        })
        .strict(),
    })
    .strict(),
]);

export type AgentDeskAction = z.infer<typeof AgentDeskActionSchema>;
export type StartResearchAction = Extract<AgentDeskAction, { type: "start_research" }>;
export type StartResearchParameters = Omit<StartResearchAction["payload"], "question">;
export type ChallengeRecommendationAction = Extract<
  AgentDeskAction,
  { type: "challenge_recommendation" }
>;
export type ResearchDeeperAction = Extract<AgentDeskAction, { type: "research_deeper" }>;
export type FocusOnCriterionAction = Extract<AgentDeskAction, { type: "focus_on_criterion" }>;
export type RetryFailedAgentAction = Extract<AgentDeskAction, { type: "retry_failed_agent" }>;

export function parseAgentDeskAction(value: unknown): AgentDeskAction {
  const serialized = JSON.stringify(value);
  if (
    serialized === undefined ||
    new TextEncoder().encode(serialized).byteLength > MAX_AG_UI_FORWARDED_PROPS_BYTES
  ) {
    throw new Error("AgentDesk action exceeds the allowed size.");
  }
  if (
    typeof value === "object" &&
    value !== null &&
    (value as Record<string, unknown>).schemaVersion !== AG_UI_ACTION_SCHEMA_VERSION
  ) {
    throw new Error(
      `Unsupported AG-UI action schema: ${String((value as Record<string, unknown>).schemaVersion)}`,
    );
  }
  const result = AgentDeskActionSchema.safeParse(value);
  if (!result.success) {
    throw new Error(`Invalid AgentDesk action: ${result.error.issues[0]?.message ?? "unknown"}`);
  }
  return result.data;
}

const DEFAULT_START_RESEARCH_PARAMETERS: StartResearchParameters = {
  options: [],
  constraints: [],
  criteria: [],
  desiredDepth: "normal",
};

export function createStartResearchAction(
  question: string,
  parameters: StartResearchParameters = DEFAULT_START_RESEARCH_PARAMETERS,
): StartResearchAction {
  return validateBuiltAction({
    schemaVersion: AG_UI_ACTION_SCHEMA_VERSION,
    actionId: crypto.randomUUID(),
    type: "start_research",
    sessionId: null,
    payload: {
      question: question.trim(),
      options: [...parameters.options],
      constraints: [...parameters.constraints],
      criteria: [...parameters.criteria],
      desiredDepth: parameters.desiredDepth,
    },
  });
}

export function createChallengeRecommendationAction(
  sessionId: string,
  challenge: string | null = null,
): ChallengeRecommendationAction {
  return validateBuiltAction({
    schemaVersion: AG_UI_ACTION_SCHEMA_VERSION,
    actionId: crypto.randomUUID(),
    type: "challenge_recommendation",
    sessionId: sessionId.trim(),
    payload: { challenge: challenge?.trim() || null },
  });
}

export function createResearchDeeperAction(
  sessionId: string,
  focusAreas: string[] = [],
): ResearchDeeperAction {
  return validateBuiltAction({
    schemaVersion: AG_UI_ACTION_SCHEMA_VERSION,
    actionId: crypto.randomUUID(),
    type: "research_deeper",
    sessionId: sessionId.trim(),
    payload: {
      focusAreas: Array.from(new Set(focusAreas.map((area) => area.trim()).filter(Boolean))),
      desiredDepth: "deep",
    },
  });
}

export function createFocusOnCriterionAction(
  sessionId: string,
  criterion: string,
): FocusOnCriterionAction {
  return validateBuiltAction({
    schemaVersion: AG_UI_ACTION_SCHEMA_VERSION,
    actionId: crypto.randomUUID(),
    type: "focus_on_criterion",
    sessionId: sessionId.trim(),
    payload: { criterion: criterion.trim() },
  });
}

export function createRetryFailedAgentAction(
  sessionId: string,
  agentId: string,
  remoteTaskId: string | null,
): RetryFailedAgentAction {
  return validateBuiltAction({
    schemaVersion: AG_UI_ACTION_SCHEMA_VERSION,
    actionId: crypto.randomUUID(),
    type: "retry_failed_agent",
    sessionId: sessionId.trim(),
    payload: {
      agentId: agentId.trim(),
      remoteTaskId: remoteTaskId?.trim() || null,
    },
  });
}

export class ActionSubmissionGate {
  #activeActionId: string | null = null;

  get activeActionId(): string | null {
    return this.#activeActionId;
  }

  begin(actionId: string): boolean {
    if (this.#activeActionId !== null) {
      return false;
    }
    this.#activeActionId = actionId;
    return true;
  }

  finish(actionId: string): void {
    if (this.#activeActionId === actionId) {
      this.#activeActionId = null;
    }
  }
}

function validateBuiltAction<Action extends AgentDeskAction>(action: Action): Action {
  return parseAgentDeskAction(action) as Action;
}
