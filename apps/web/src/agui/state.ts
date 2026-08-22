import { z } from "zod";

export const AG_UI_STATE_SCHEMA_VERSION = "1.0" as const;
export const MAX_AG_UI_STATE_BYTES = 256 * 1024;
export const MAX_RENDERED_TEXT_LENGTH = 16 * 1024;

const nonEmptyText = z.string().trim().min(1).max(MAX_RENDERED_TEXT_LENGTH);
const unitInterval = z.number().finite().min(0).max(1);
const optionScore = z.number().finite().min(0).max(10);
const safeHttpUrl = z
  .string()
  .url()
  .refine((value) => {
    const protocol = new URL(value).protocol;
    return protocol === "http:" || protocol === "https:";
  }, "Source URLs must use HTTP or HTTPS.");

const evidenceSchema = z
  .object({
    id: nonEmptyText,
    title: nonEmptyText,
    sourceUrl: safeHttpUrl.nullable(),
    sourceType: z.enum([
      "official_documentation",
      "primary_source",
      "secondary_source",
      "user_provided",
      "fixture",
    ]),
    summary: nonEmptyText,
    relevance: unitInterval,
    retrievedAt: z.string().datetime({ offset: true }),
  })
  .strict();

const claimSchema = z
  .object({
    id: nonEmptyText,
    statement: nonEmptyText,
    evidenceIds: z.array(nonEmptyText).min(1),
    confidence: unitInterval.nullable().default(null),
    caveats: z.array(nonEmptyText).default([]),
  })
  .strict();

const criterionScoreSchema = z
  .object({
    criterion: nonEmptyText,
    weight: unitInterval,
    scores: z.record(nonEmptyText, optionScore),
    rationale: nonEmptyText,
    supportingClaimIds: z.array(nonEmptyText),
  })
  .strict();

const decisionAnalysisSchema = z
  .object({
    recommendation: nonEmptyText,
    executiveSummary: nonEmptyText,
    criteria: z.array(criterionScoreSchema).min(1),
    argumentsFor: z.array(nonEmptyText).min(1),
    argumentsAgainst: z.array(nonEmptyText).min(1),
    assumptions: z.array(nonEmptyText).min(1),
    risks: z.array(nonEmptyText).min(1),
    recommendationChangesIf: z.array(nonEmptyText).min(1),
  })
  .strict();

const recommendationChallengeSchema = z
  .object({
    currentRecommendation: nonEmptyText,
    strongestAlternative: nonEmptyText,
    strongestCounterargument: nonEmptyText,
    supportingClaimIds: z.array(nonEmptyText).min(1),
    assumptions: z.array(nonEmptyText).min(1),
    evidenceGaps: z.array(nonEmptyText).default([]),
    recommendationChangesIf: z.array(nonEmptyText).min(1),
  })
  .strict();

const verificationReportSchema = z
  .object({
    results: z.array(
      z
        .object({
          claimId: nonEmptyText,
          verdict: z.enum([
            "supported",
            "partially_supported",
            "contradicted",
            "insufficient_evidence",
          ]),
          rationale: nonEmptyText,
          evidenceIds: z.array(nonEmptyText),
        })
        .strict(),
    ),
  })
  .strict();

const specialistViewSchema = z
  .object({
    agentId: nonEmptyText,
    name: nonEmptyText,
    skill: nonEmptyText,
    status: z.enum(["pending", "working", "waiting", "completed", "cancelled", "failed"]),
    remoteTaskId: nonEmptyText.nullable().default(null),
    message: nonEmptyText.nullable().default(null),
  })
  .strict();

const followUpActionSchema = z.enum([
  "challenge_recommendation",
  "research_deeper",
  "focus_on_criterion",
  "retry_failed_agent",
]);

export const AgentDeskViewStateSchema = z
  .object({
    schemaVersion: z.literal(AG_UI_STATE_SCHEMA_VERSION),
    sessionId: nonEmptyText.nullable().default(null),
    question: nonEmptyText.nullable().default(null),
    status: z.enum([
      "idle",
      "planning",
      "researching",
      "analyzing",
      "verifying",
      "cancelling",
      "completed",
      "cancelled",
      "failed",
      "partial",
    ]).default("idle"),
    activeStep: nonEmptyText.nullable().default(null),
    agents: z.array(specialistViewSchema).default([]),
    evidence: z.array(evidenceSchema).default([]),
    evidenceCount: z.number().int().nonnegative().default(0),
    claims: z.array(claimSchema).default([]),
    analysis: decisionAnalysisSchema.nullable().default(null),
    recommendationChallenge: recommendationChallengeSchema.nullable().default(null),
    verification: verificationReportSchema.nullable().default(null),
    warnings: z.array(nonEmptyText).default([]),
    errors: z.array(nonEmptyText).default([]),
    availableActions: z.array(followUpActionSchema).default([]),
    lastUpdatedAt: z.string().datetime({ offset: true }).nullable().default(null),
  })
  .strict()
  .superRefine((state, context) => {
    if (
      state.status !== "idle" &&
      (state.sessionId === null || state.question === null || state.lastUpdatedAt === null)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Active AG-UI state requires session, question, and update timestamp.",
      });
    }
    if (state.evidenceCount !== state.evidence.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "evidenceCount must equal the number of evidence items.",
      });
    }
    const unique = (values: string[]) => new Set(values).size === values.length;
    if (!unique(state.agents.map((agent) => agent.agentId))) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "Agent IDs must be unique." });
    }
    if (!unique(state.evidence.map((evidence) => evidence.id))) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "Evidence IDs must be unique." });
    }
    if (!unique(state.claims.map((claim) => claim.id))) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: "Claim IDs must be unique." });
    }
    const evidenceIds = new Set(state.evidence.map((evidence) => evidence.id));
    if (state.claims.some((claim) => claim.evidenceIds.some((id) => !evidenceIds.has(id)))) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Claims must reference evidence present in state.",
      });
    }
    if (!unique(state.availableActions)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Available actions must not contain duplicates.",
      });
    }
    if (state.status === "failed" && state.errors.length === 0) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Failed AG-UI state requires a user-visible error.",
      });
    }
  });

export type AgentDeskViewState = z.infer<typeof AgentDeskViewStateSchema>;

export const INITIAL_AGENTDESK_STATE: AgentDeskViewState = {
  schemaVersion: AG_UI_STATE_SCHEMA_VERSION,
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
};

export function parseAgentDeskViewState(value: unknown): AgentDeskViewState {
  requireJsonSize(value, MAX_AG_UI_STATE_BYTES, "AG-UI state");
  if (
    typeof value === "object" &&
    value !== null &&
    (value as Record<string, unknown>).schemaVersion !== AG_UI_STATE_SCHEMA_VERSION
  ) {
    throw new Error(
      `Unsupported AG-UI state schema: ${String((value as Record<string, unknown>).schemaVersion)}`,
    );
  }
  const result = AgentDeskViewStateSchema.safeParse(value);
  if (!result.success) {
    const issue = result.error.issues[0];
    const location = issue?.path.join(".");
    throw new Error(
      `Invalid AG-UI state${location ? ` at ${location}` : ""}: ${issue?.message ?? "unknown"}`,
    );
  }
  return result.data;
}

function requireJsonSize(value: unknown, maximum: number, label: string): void {
  let encoded: string;
  try {
    encoded = JSON.stringify(value);
  } catch {
    throw new Error(`${label} must be JSON-safe.`);
  }
  if (encoded === undefined || new TextEncoder().encode(encoded).byteLength > maximum) {
    throw new Error(`${label} exceeds the allowed size.`);
  }
}
