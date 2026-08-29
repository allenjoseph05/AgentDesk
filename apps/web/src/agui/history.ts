import { z } from "zod";

import { parseAgentDeskViewState, type AgentDeskViewState } from "./state";

const nonEmptyText = z.string().trim().min(1).max(16 * 1024);
const historyItemSchema = z
  .object({
    sessionId: nonEmptyText,
    threadId: nonEmptyText,
    question: nonEmptyText,
    status: z.enum([
      "created",
      "scoping",
      "awaiting_input",
      "planning",
      "researching",
      "analyzing",
      "verifying",
      "cancelling",
      "completed",
      "partial",
      "failed",
      "cancelled",
    ]),
    lastRunId: nonEmptyText.nullable(),
    createdAt: z.string().datetime({ offset: true }),
    updatedAt: z.string().datetime({ offset: true }),
  })
  .strict();

const historyPageSchema = z.object({ sessions: z.array(historyItemSchema).max(100) }).strict();
const MAX_HISTORY_BYTES = 512 * 1024;
const TERMINAL_STATUSES = new Set(["completed", "partial", "failed", "cancelled"]);

export type SessionHistoryItem = z.infer<typeof historyItemSchema>;

export interface SessionHistoryDetail {
  session: SessionHistoryItem;
  state: AgentDeskViewState;
}

export async function listSessionHistory(
  threadId: string,
  fetcher: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<SessionHistoryItem[]> {
  const response = await fetcher(`/api/sessions?limit=50&threadId=${encodeURIComponent(threadId)}`);
  return historyPageSchema
    .parse(await readJson(response))
    .sessions.filter((session) => TERMINAL_STATUSES.has(session.status));
}

export async function getSessionHistory(
  sessionId: string,
  fetcher: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<SessionHistoryDetail> {
  const response = await fetcher(`/api/sessions/${encodeURIComponent(sessionId)}`);
  const value = await readJson(response);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Session history response is invalid.");
  }
  const record = value as Record<string, unknown>;
  if (!Object.hasOwn(record, "session") || !Object.hasOwn(record, "state")) {
    throw new Error("Session history response is incomplete.");
  }
  return {
    session: historyItemSchema.parse(record.session),
    state: parseAgentDeskViewState(record.state),
  };
}

async function readJson(response: Response): Promise<unknown> {
  if (!response.ok) {
    throw new Error(`Session history request failed with status ${response.status}.`);
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_HISTORY_BYTES) {
    throw new Error("Session history response exceeds the allowed size.");
  }
  return JSON.parse(text) as unknown;
}
