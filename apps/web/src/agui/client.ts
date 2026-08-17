import { HttpAgent, type AgentSubscriber, type HttpAgentFetchFn } from "@ag-ui/client";

import { createStartResearchAction, parseAgentDeskAction } from "./actions.ts";
import {
  INITIAL_AGENTDESK_STATE,
  parseAgentDeskViewState,
  type AgentDeskViewState,
} from "./state.ts";

export const AG_UI_ENDPOINT = "/ag-ui";

export interface AgentDeskRunObserver {
  onRunning?(): void;
  onState?(state: AgentDeskViewState): void;
  onMessage?(message: string): void;
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

  agent.addMessage({
    id: crypto.randomUUID(),
    role: "user",
    content: normalizedQuestion,
  });
  const action = parseAgentDeskAction(createStartResearchAction(normalizedQuestion));
  const abortController = new AbortController();

  const subscriber: AgentSubscriber = {
    onRunStartedEvent: () => observer.onRunning?.(),
    onStateChanged: ({ state }) => observer.onState?.(parseAgentDeskViewState(state)),
    onTextMessageContentEvent: ({ event, textMessageBuffer }) =>
      observer.onMessage?.(`${textMessageBuffer}${event.delta}`),
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
