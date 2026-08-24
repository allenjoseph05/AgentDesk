import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  ActionSubmissionGate,
  type AgentDeskAction,
  createChallengeRecommendationAction,
  createFocusOnCriterionAction,
  createResearchDeeperAction,
  createRetryFailedAgentAction,
  createStartResearchAction,
} from "../agui/actions";
import { createCoordinatorAgent, runAgentDeskAction } from "../agui/client";
import { userSafeAgUiError } from "../agui/client-config";
import { useAgentDeskStateStore } from "../agui/store-react";
import { type TimelineItem, upsertTimelineItem } from "../agui/timeline";
import { agentDeskRuntimeMode, DEMO_RESEARCH_PARAMETERS } from "./runtime-mode";

export type RuntimePhase = "idle" | "connecting" | "running" | "error";

interface AgentDeskRuntimeValue {
  activeAction: AgentDeskAction["type"] | null;
  cancelRun(): void;
  challengeRecommendation(sessionId: string, challenge: string | null): Promise<boolean>;
  error: string | null;
  focusOnCriterion(sessionId: string, criterion: string): Promise<boolean>;
  message: string;
  phase: RuntimePhase;
  researchDeeper(sessionId: string, focusAreas: string[]): Promise<boolean>;
  retryFailedAgent(
    sessionId: string,
    agentId: string,
    remoteTaskId: string | null,
  ): Promise<boolean>;
  startResearch(question: string): Promise<boolean>;
  threadId: string;
  timeline: TimelineItem[];
}

interface AgentDeskRuntimeProviderProps {
  children: ReactNode;
  createAgent?: () => ReturnType<typeof createCoordinatorAgent>;
}

const AgentDeskRuntimeContext = createContext<AgentDeskRuntimeValue | null>(null);

export function AgentDeskRuntimeProvider({
  children,
  createAgent = createCoordinatorAgent,
}: AgentDeskRuntimeProviderProps) {
  const agentRef = useRef<ReturnType<typeof createCoordinatorAgent> | null>(null);
  agentRef.current ??= createAgent();
  const agent = agentRef.current;
  const submissionGateRef = useRef<ActionSubmissionGate | null>(null);
  submissionGateRef.current ??= new ActionSubmissionGate();
  const submissionGate = submissionGateRef.current;
  const stateStore = useAgentDeskStateStore();

  const [phase, setPhase] = useState<RuntimePhase>("idle");
  const [activeAction, setActiveAction] = useState<AgentDeskAction["type"] | null>(null);
  const [message, setMessage] = useState("Ready for a new research question.");
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);

  useEffect(
    () =>
      stateStore.subscribeRehydration((request) => {
        setError(`A malformed AG-UI ${request.cause} was rejected. ${request.message}`);
        setMessage("The last valid state is preserved; rehydration is required.");
        setPhase("error");
      }),
    [stateStore],
  );

  const executeAction = useCallback(async (
    actionFactory: () => AgentDeskAction,
    userMessage: string,
  ): Promise<boolean> => {
    let action: AgentDeskAction;
    try {
      action = actionFactory();
    } catch (actionError) {
      setError(userSafeAgUiError(actionError));
      setMessage("The action was not sent because its payload is invalid.");
      setPhase("error");
      return false;
    }

    if (!submissionGate.begin(action.actionId)) {
      return false;
    }

    setError(null);
    setActiveAction(action.type);
    setPhase("connecting");
    setMessage("Connecting to the Coordinator...");
    try {
      await runAgentDeskAction(agent, action, userMessage, {
        onDelta: stateStore.applyDelta,
        onRunning: () => setPhase("running"),
        onSnapshot: stateStore.replaceSnapshot,
        onMessage: setMessage,
        onTimelineItem: (item) => setTimeline((items) => upsertTimelineItem(items, item)),
        onFinished: () => setPhase((current) => (current === "error" ? current : "idle")),
        onCancelled: () => {
          setMessage("Research run cancelled.");
          setPhase("idle");
        },
        onError: (runError) => {
          setError(runError);
          setPhase("error");
        },
      });
      return true;
    } catch (runError) {
      setError(userSafeAgUiError(runError));
      setPhase("error");
      return false;
    } finally {
      submissionGate.finish(action.actionId);
      setActiveAction(null);
    }
  }, [agent, stateStore, submissionGate]);

  const startResearch = useCallback(
    (question: string) =>
      executeAction(
        () =>
          createStartResearchAction(
            question,
            agentDeskRuntimeMode === "demo" ? DEMO_RESEARCH_PARAMETERS : undefined,
          ),
        question,
      ),
    [executeAction],
  );

  const challengeRecommendation = useCallback(
    (sessionId: string, challenge: string | null) =>
      executeAction(
        () => createChallengeRecommendationAction(sessionId, challenge),
        challenge?.trim()
          ? challenge.trim()
          : "Challenge the current recommendation and test the strongest counterargument.",
      ),
    [executeAction],
  );

  const researchDeeper = useCallback(
    (sessionId: string, focusAreas: string[]) =>
      executeAction(
        () => createResearchDeeperAction(sessionId, focusAreas),
        focusAreas.length > 0
          ? `Research deeper into: ${focusAreas.join(", ")}.`
          : "Research this question more deeply.",
      ),
    [executeAction],
  );

  const focusOnCriterion = useCallback(
    (sessionId: string, criterion: string) =>
      executeAction(
        () => createFocusOnCriterionAction(sessionId, criterion),
        `Focus the analysis on ${criterion.trim()}.`,
      ),
    [executeAction],
  );

  const retryFailedAgent = useCallback(
    (sessionId: string, agentId: string, remoteTaskId: string | null) =>
      executeAction(
        () => createRetryFailedAgentAction(sessionId, agentId, remoteTaskId),
        `Retry the failed specialist ${agentId.trim()}.`,
      ),
    [executeAction],
  );

  const cancelRun = useCallback(() => {
    setMessage("Stopping the active run...");
    agentRef.current?.abortRun();
  }, []);

  const value = useMemo<AgentDeskRuntimeValue>(
    () => ({
      activeAction,
      cancelRun,
      challengeRecommendation,
      error,
      focusOnCriterion,
      message,
      phase,
      researchDeeper,
      retryFailedAgent,
      startResearch,
      threadId: agent.threadId,
      timeline,
    }),
    [
      activeAction,
      agent,
      cancelRun,
      challengeRecommendation,
      error,
      focusOnCriterion,
      message,
      phase,
      researchDeeper,
      retryFailedAgent,
      startResearch,
      timeline,
    ],
  );

  return (
    <AgentDeskRuntimeContext.Provider value={value}>
      {children}
    </AgentDeskRuntimeContext.Provider>
  );
}

export function useAgentDeskRuntime(): AgentDeskRuntimeValue {
  const runtime = useContext(AgentDeskRuntimeContext);
  if (runtime === null) {
    throw new Error("useAgentDeskRuntime must be used inside AgentDeskRuntimeProvider.");
  }
  return runtime;
}
