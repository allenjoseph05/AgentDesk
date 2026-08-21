import { HttpAgent, type AgentSubscriber, type HttpAgentFetchFn } from "@ag-ui/client";

import {
  type AgentDeskAction,
  createStartResearchAction,
  parseAgentDeskAction,
} from "./actions.ts";
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

export const AG_UI_ENDPOINT = "/ag-ui";

export interface AgentDeskRunObserver {
  onDelta?(delta: unknown): boolean;
  onRunning?(): void;
  onSnapshot?(snapshot: unknown): boolean;
  onState?(state: AgentDeskViewState): void;
  onMessage?(message: string): void;
  onTimelineItem?(item: TimelineItem): void;
  onFinished?(): void;
  onCancelled?(): void;
  onError?(message: string): void;
}

export function createCoordinatorAgent(
  fetch?: HttpAgentFetchFn,
  threadId = crypto.randomUUID(),
): HttpAgent {
  return new HttpAgent({
    agentId: "agentdesk-coordinator",
    description: "AgentDesk browser-to-Coordinator AG-UI connection",
    url: AG_UI_ENDPOINT,
    threadId,
    initialState: structuredClone(INITIAL_AGENTDESK_STATE),
    ...(fetch ? { fetch } : {}),
  });
}

export async function runResearch(
  agent: HttpAgent,
  question: string,
  observer: AgentDeskRunObserver = {},
): Promise<void> {
  const normalizedQuestion = question.trim();
  if (!normalizedQuestion) {
    throw new Error("A research question is required.");
  }

  await runAgentDeskAction(
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
): Promise<void> {
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
    onRunErrorEvent: ({ event }) => observer.onError?.(event.message),
  };

  await agent.runAgent(
    { abortController, forwardedProps: { agentdesk: action } },
    subscriber,
  );
  if (abortController.signal.aborted) {
    observer.onCancelled?.();
  }
}

function activityContentFromItem(item: Extract<TimelineItem, { kind: "activity" }>) {
  return {
    ...(item.agentId === null ? {} : { agentId: item.agentId }),
    status: item.status,
    summary: item.summary,
  };
}
