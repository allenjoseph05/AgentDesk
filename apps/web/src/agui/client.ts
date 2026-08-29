import { HttpAgent, type AgentSubscriber, type HttpAgentFetchFn } from "@ag-ui/client";

import {
  type AgentDeskAction,
  createStartResearchAction,
  parseAgentDeskAction,
} from "./actions.ts";
import {
  type AuthenticationHeaderProvider,
  type BrowserClientEnvironment,
  type BrowserStorage,
  createAuthenticatedFetch,
  DEFAULT_AG_UI_ENDPOINT,
  getOrCreateBrowserThreadId,
  resolveAgUiEndpoint,
  userSafeAgUiError,
} from "./client-config.ts";
import {
  INITIAL_AGENTDESK_STATE,
  parseAgentDeskViewState,
  type AgentDeskViewState,
} from "./state.ts";
import {
  applySafeActivityPatch,
  createActivityTimelineItem,
  semanticLabel,
  type TimelineItem,
} from "./timeline.ts";
import { A2UI_SURFACE_EVENT_NAME } from "../a2ui/contracts.ts";

export const AG_UI_ENDPOINT = DEFAULT_AG_UI_ENDPOINT;

export interface AgentDeskRunIdentity {
  actionId: string;
  runId: string;
  threadId: string;
}

export interface BrowserCoordinatorAgentOptions {
  environment?: BrowserClientEnvironment;
  fetch?: HttpAgentFetchFn;
  getAuthenticationHeaders?: AuthenticationHeaderProvider;
  storage?: BrowserStorage | null;
  threadId?: string;
}

export interface AgentDeskRunObserver {
  onA2uiSurface?(value: unknown): boolean;
  onDelta?(delta: unknown): boolean;
  onRunning?(): void;
  onSnapshot?(snapshot: unknown): boolean;
  onState?(state: AgentDeskViewState): void;
  onMessage?(message: string): void;
  onRunIdentity?(identity: AgentDeskRunIdentity): void;
  onTimelineItem?(item: TimelineItem): void;
  onFinished?(): void;
  onCancelled?(): void;
  onError?(message: string): void;
}

export function createCoordinatorAgent(
  fetch?: HttpAgentFetchFn,
  threadId = crypto.randomUUID(),
): HttpAgent {
  return buildCoordinatorAgent({ endpoint: AG_UI_ENDPOINT, fetch, threadId });
}

export function createBrowserCoordinatorAgent(
  options: BrowserCoordinatorAgentOptions = {},
): HttpAgent {
  const storage = options.storage === undefined ? availableSessionStorage() : options.storage;
  const threadId = options.threadId ?? getOrCreateBrowserThreadId(storage);
  const baseFetch = options.fetch ?? globalThis.fetch.bind(globalThis);
  return buildCoordinatorAgent({
    endpoint: resolveAgUiEndpoint(options.environment ?? {}),
    fetch: createAuthenticatedFetch(baseFetch, options.getAuthenticationHeaders),
    threadId,
  });
}

function buildCoordinatorAgent({
  endpoint,
  fetch,
  threadId,
}: {
  endpoint: string;
  fetch?: HttpAgentFetchFn;
  threadId: string;
}): HttpAgent {
  return new HttpAgent({
    agentId: "agentdesk-coordinator",
    description: "AgentDesk browser-to-Coordinator AG-UI connection",
    url: endpoint,
    threadId,
    initialState: structuredClone(INITIAL_AGENTDESK_STATE),
    ...(fetch ? { fetch } : {}),
  });
}

export async function runResearch(
  agent: HttpAgent,
  question: string,
  observer: AgentDeskRunObserver = {},
): Promise<AgentDeskRunIdentity> {
  const normalizedQuestion = question.trim();
  if (!normalizedQuestion) {
    throw new Error("A research question is required.");
  }

  return runAgentDeskAction(
    agent,
    createStartResearchAction(normalizedQuestion),
    normalizedQuestion,
    observer,
  );
}

export async function runAgentDeskAction(
  agent: HttpAgent,
  actionInput: AgentDeskAction,
  userMessage: string,
  observer: AgentDeskRunObserver = {},
): Promise<AgentDeskRunIdentity> {
  const action = parseAgentDeskAction(actionInput);
  const normalizedMessage = userMessage.trim();
  if (!normalizedMessage) {
    throw new Error("A user-facing action message is required.");
  }

  agent.addMessage({
    id: crypto.randomUUID(),
    role: "user",
    content: normalizedMessage,
  });
  const abortController = new AbortController();
  const activityContent = new Map<string, Record<string, unknown>>();
  const identity = {
    actionId: action.actionId,
    runId: crypto.randomUUID(),
    threadId: agent.threadId,
  } satisfies AgentDeskRunIdentity;
  observer.onRunIdentity?.(identity);

  const subscriber: AgentSubscriber = {
    onRunStartedEvent: () => observer.onRunning?.(),
    onStepStartedEvent: ({ event, input }) =>
      observer.onTimelineItem?.({
        id: `step:${input.runId}:${event.stepName}`,
        runId: input.runId,
        timestamp: event.timestamp ?? null,
        kind: "step",
        label: semanticLabel(event.stepName),
        status: "active",
        stepName: event.stepName,
      }),
    onStepFinishedEvent: ({ event, input }) =>
      observer.onTimelineItem?.({
        id: `step:${input.runId}:${event.stepName}`,
        runId: input.runId,
        timestamp: event.timestamp ?? null,
        kind: "step",
        label: semanticLabel(event.stepName),
        status: "complete",
        stepName: event.stepName,
      }),
    onStateSnapshotEvent: ({ event }) =>
      observer.onSnapshot?.(event.snapshot) === false
        ? { stopPropagation: true }
        : undefined,
    onStateDeltaEvent: ({ event }) =>
      observer.onDelta?.(event.delta) === false
        ? { stopPropagation: true }
        : undefined,
    onCustomEvent: ({ event }) => {
      if (event.name !== A2UI_SURFACE_EVENT_NAME) return undefined;
      return observer.onA2uiSurface?.(event.value) === false
        ? { stopPropagation: true }
        : undefined;
    },
    onStateChanged: ({ state }) => {
      if (observer.onState !== undefined) {
        observer.onState(parseAgentDeskViewState(state));
      }
    },
    onTextMessageStartEvent: ({ event, input }) =>
      observer.onTimelineItem?.({
        id: `message:${input.runId}:${event.messageId}`,
        runId: input.runId,
        timestamp: event.timestamp ?? null,
        kind: "message",
        content: "",
        role: "assistant",
        status: "streaming",
      }),
    onTextMessageContentEvent: ({ event, input, textMessageBuffer }) => {
      const content = `${textMessageBuffer}${event.delta}`;
      observer.onMessage?.(content);
      observer.onTimelineItem?.({
        id: `message:${input.runId}:${event.messageId}`,
        runId: input.runId,
        timestamp: event.timestamp ?? null,
        kind: "message",
        content,
        role: "assistant",
        status: "streaming",
      });
    },
    onTextMessageEndEvent: ({ event, input, textMessageBuffer }) =>
      observer.onTimelineItem?.({
        id: `message:${input.runId}:${event.messageId}`,
        runId: input.runId,
        timestamp: event.timestamp ?? null,
        kind: "message",
        content: textMessageBuffer,
        role: "assistant",
        status: "complete",
      }),
    onActivitySnapshotEvent: ({ activityMessage, event, input }) => {
      const item = createActivityTimelineItem({
        activityType: event.activityType,
        content: activityMessage?.content ?? event.content,
        messageId: event.messageId,
        runId: input.runId,
        timestamp: event.timestamp,
      });
      if (item !== null) {
        activityContent.set(event.messageId, activityContentFromItem(item));
        observer.onTimelineItem?.(item);
      }
    },
    onActivityDeltaEvent: ({ activityMessage, event, input }) => {
      const content = applySafeActivityPatch(
        activityContent.get(event.messageId) ?? activityMessage?.content ?? {},
        event.patch,
      );
      const item = createActivityTimelineItem({
        activityType: event.activityType,
        content,
        messageId: event.messageId,
        runId: input.runId,
        timestamp: event.timestamp,
      });
      if (item !== null) {
        activityContent.set(event.messageId, activityContentFromItem(item));
        observer.onTimelineItem?.(item);
      }
    },
    onRunFinishedEvent: () => observer.onFinished?.(),
    onRunErrorEvent: ({ event }) => observer.onError?.(userSafeAgUiError(event.message)),
  };

  await agent.runAgent(
    { abortController, forwardedProps: { agentdesk: action }, runId: identity.runId },
    subscriber,
  );
  if (abortController.signal.aborted) {
    observer.onCancelled?.();
  }
  return identity;
}

function activityContentFromItem(item: Extract<TimelineItem, { kind: "activity" }>) {
  return {
    ...(item.agentId === null ? {} : { agentId: item.agentId }),
    status: item.status,
    summary: item.summary,
  };
}

function availableSessionStorage(): BrowserStorage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}
