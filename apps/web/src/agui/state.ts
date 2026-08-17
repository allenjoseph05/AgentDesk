export const AG_UI_STATE_SCHEMA_VERSION = "1.0" as const;

export type AgentDeskStatus =
  | "idle"
  | "planning"
  | "researching"
  | "analyzing"
  | "verifying"
  | "completed"
  | "cancelled"
  | "failed"
  | "partial";

export interface AgentDeskViewState {
  schemaVersion: typeof AG_UI_STATE_SCHEMA_VERSION;
  sessionId: string | null;
  question: string | null;
  status: AgentDeskStatus;
  activeStep: string | null;
  evidenceCount: number;
  warnings: string[];
  errors: string[];
}

export const INITIAL_AGENTDESK_STATE: AgentDeskViewState = {
  schemaVersion: AG_UI_STATE_SCHEMA_VERSION,
  sessionId: null,
  question: null,
  status: "idle",
  activeStep: null,
  evidenceCount: 0,
  warnings: [],
  errors: [],
};

const statuses = new Set<AgentDeskStatus>([
  "idle",
  "planning",
  "researching",
  "analyzing",
  "verifying",
  "completed",
  "cancelled",
  "failed",
  "partial",
]);

export function parseAgentDeskViewState(value: unknown): AgentDeskViewState {
  if (typeof value !== "object" || value === null) {
    throw new Error("AG-UI state must be an object.");
  }
  const state = value as Record<string, unknown>;
  if (state.schemaVersion !== AG_UI_STATE_SCHEMA_VERSION) {
    throw new Error(`Unsupported AG-UI state schema: ${String(state.schemaVersion)}`);
  }
  if (typeof state.status !== "string" || !statuses.has(state.status as AgentDeskStatus)) {
    throw new Error(`Unknown AgentDesk status: ${String(state.status)}`);
  }
  if (!Number.isInteger(state.evidenceCount) || (state.evidenceCount as number) < 0) {
    throw new Error("AG-UI evidenceCount must be a non-negative integer.");
  }
  for (const key of ["warnings", "errors"] as const) {
    if (!Array.isArray(state[key]) || !state[key].every((item) => typeof item === "string")) {
      throw new Error(`AG-UI ${key} must be an array of strings.`);
    }
  }
  for (const key of ["sessionId", "question", "activeStep"] as const) {
    if (state[key] !== null && typeof state[key] !== "string") {
      throw new Error(`AG-UI ${key} must be a string or null.`);
    }
  }
  return {
    schemaVersion: AG_UI_STATE_SCHEMA_VERSION,
    sessionId: state.sessionId as string | null,
    question: state.question as string | null,
    status: state.status as AgentDeskStatus,
    activeStep: state.activeStep as string | null,
    evidenceCount: state.evidenceCount as number,
    warnings: [...(state.warnings as string[])],
    errors: [...(state.errors as string[])],
  };
}
