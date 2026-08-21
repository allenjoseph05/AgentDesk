export const MAX_TIMELINE_ITEMS = 50;

interface TimelineBase {
  id: string;
  runId: string;
  timestamp: number | null;
}

export interface TimelineMessageItem extends TimelineBase {
  content: string;
  kind: "message";
  role: "assistant" | "user";
  status: "complete" | "streaming";
}

export interface TimelineStepItem extends TimelineBase {
  kind: "step";
  label: string;
  status: "active" | "complete";
  stepName: string;
}

export interface TimelineActivityItem extends TimelineBase {
  activityType: string;
  agentId: string | null;
  kind: "activity";
  status: "cancelled" | "completed" | "failed" | "waiting" | "working";
  summary: string;
}

export type TimelineItem = TimelineMessageItem | TimelineStepItem | TimelineActivityItem;

const ACTIVITY_STATUSES = new Set<TimelineActivityItem["status"]>([
  "working",
  "waiting",
  "completed",
  "failed",
  "cancelled",
]);
const ACTIVITY_PATCH_PATHS = new Set([
  "/agentId",
  "/message",
  "/specialistId",
  "/status",
  "/summary",
]);

export function upsertTimelineItem(
  items: readonly TimelineItem[],
  item: TimelineItem,
): TimelineItem[] {
  const existingIndex = items.findIndex((candidate) => candidate.id === item.id);
  const next = [...items];
  if (existingIndex === -1) {
    next.push(item);
  } else {
    next[existingIndex] = item;
  }
  return next.slice(-MAX_TIMELINE_ITEMS);
}

export function createActivityTimelineItem(input: {
  activityType: string;
  content: unknown;
  messageId: string;
  runId: string;
  timestamp?: number;
}): TimelineActivityItem | null {
  if (!isRecord(input.content)) {
    return null;
  }
  const summary = safeText(input.content.summary) ?? safeText(input.content.message);
  if (summary === null) {
    return null;
  }
  const suppliedStatus = safeText(input.content.status);
  const status = ACTIVITY_STATUSES.has(suppliedStatus as TimelineActivityItem["status"])
    ? suppliedStatus as TimelineActivityItem["status"]
    : "working";
  return {
    id: `activity:${input.runId}:${input.messageId}`,
    runId: input.runId,
    timestamp: input.timestamp ?? null,
    kind: "activity",
    activityType: input.activityType,
    agentId: safeText(input.content.agentId) ?? safeText(input.content.specialistId),
    status,
    summary,
  };
}

export function applySafeActivityPatch(
  current: Record<string, unknown>,
  patch: unknown,
): Record<string, unknown> {
  const next = { ...current };
  if (!Array.isArray(patch)) {
    return next;
  }
  for (const operation of patch) {
    if (!isRecord(operation) || !ACTIVITY_PATCH_PATHS.has(String(operation.path))) {
      continue;
    }
    const key = String(operation.path).slice(1);
    if (operation.op === "remove") {
      delete next[key];
    } else if (
      (operation.op === "add" || operation.op === "replace") &&
      typeof operation.value === "string"
    ) {
      next[key] = operation.value;
    }
  }
  return next;
}

export function semanticLabel(value: string): string {
  const normalized = value.replaceAll("-", " ").replaceAll("_", " ").trim();
  return normalized ? `${normalized.charAt(0).toUpperCase()}${normalized.slice(1)}` : "Activity";
}

function safeText(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized ? normalized.slice(0, 500) : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
