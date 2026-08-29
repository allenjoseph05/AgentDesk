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
  createPrepareResearchAction,
  createResearchDeeperAction,
  createRetryFailedAgentAction,
  createSkipIntakeAction,
  createStartResearchAction,
  createSubmitIntakeAction,
  type StartResearchParameters,
} from "../agui/actions";
import { createCoordinatorAgent, runAgentDeskAction } from "../agui/client";
import { userSafeAgUiError } from "../agui/client-config";
import {
  getSessionHistory,
  listSessionHistory,
  type SessionHistoryItem,
} from "../agui/history";
import { useAgentDeskStateStore } from "../agui/store-react";
import { type TimelineItem, upsertTimelineItem } from "../agui/timeline";
import {
  isCurrentIntakeSurface,
  type IntakeAnswers,
  parseA2uiSurfaceEvent,
  type TrustedIntakeSurface,
} from "../a2ui/contracts";
import {
  adaptiveIntakeEnabled,
  agentDeskRuntimeMode,
  DEMO_RESEARCH_PARAMETERS,
} from "./runtime-mode";

export type RuntimePhase = "idle" | "connecting" | "running" | "error";

interface AgentDeskRuntimeValue {
  activeAction: AgentDeskAction["type"] | null;
  cancelRun(): void;
  challengeRecommendation(sessionId: string, challenge: string | null): Promise<boolean>;
  error: string | null;
  focusOnCriterion(sessionId: string, criterion: string): Promise<boolean>;
  history: SessionHistoryItem[];
  intakeSurface: TrustedIntakeSurface | null;
  message: string;
  phase: RuntimePhase;
  researchDeeper(sessionId: string, focusAreas: string[]): Promise<boolean>;
  rehydrateSession(sessionId: string): Promise<boolean>;
  retryFailedAgent(
    sessionId: string,
    agentId: string,
    remoteTaskId: string | null,
  ): Promise<boolean>;
  startResearch(question: string): Promise<boolean>;
  startDirectResearch(
    question: string,
    parameters: StartResearchParameters,
  ): Promise<boolean>;
  skipIntake(surface: TrustedIntakeSurface): Promise<boolean>;
  submitIntake(surface: TrustedIntakeSurface, answers: IntakeAnswers): Promise<boolean>;
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
  const [intakeSurface, setIntakeSurface] = useState<TrustedIntakeSurface | null>(null);
  const [history, setHistory] = useState<SessionHistoryItem[]>([]);

  const refreshHistory = useCallback(async () => {
    try {
      setHistory(await listSessionHistory(agent.threadId));
    } catch {
      // History is supplementary; a read failure must not block a live run.
    }
  }, [agent.threadId]);

  const restoreCancelledSession = useCallback(
    async (sessionId: string | null) => {
      if (sessionId === null) return;
      for (let attempt = 0; attempt < 20; attempt += 1) {
        try {
          const detail = await getSessionHistory(sessionId);
          if (detail.session.threadId === agent.threadId) {
            stateStore.replaceSnapshot(detail.state);
            await refreshHistory();
            return;
          }
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
      }
    },
    [agent.threadId, refreshHistory, stateStore],
  );

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

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
    let admittedRunId: string | null = null;
    try {
      await runAgentDeskAction(agent, action, userMessage, {
        onA2uiSurface: (value) => {
          try {
            const candidate = parseA2uiSurfaceEvent(value);
            if (!isCurrentIntakeSurface(candidate, stateStore.getSnapshot())) {
              throw new Error("The A2UI intake surface is stale for the current session.");
            }
            setIntakeSurface(candidate);
            return true;
          } catch (surfaceError) {
            setError(userSafeAgUiError(surfaceError));
            setMessage("An untrusted or stale intake surface was rejected.");
            setPhase("error");
            return false;
          }
        },
        onDelta: stateStore.applyDelta,
        onRunning: () => setPhase("running"),
        onSnapshot: stateStore.replaceSnapshot,
        onState: (state) => {
          if (state.status !== "awaiting_input") setIntakeSurface(null);
        },
        onMessage: setMessage,
        onRunIdentity: ({ runId }) => {
          admittedRunId = runId;
        },
        onTimelineItem: (item) => setTimeline((items) => upsertTimelineItem(items, item)),
        onFinished: () => {
          setPhase((current) => (current === "error" ? current : "idle"));
          void refreshHistory();
        },
        onCancelled: () => {
          void restoreCancelledSession(stateStore.getSnapshot().sessionId ?? admittedRunId);
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
  }, [agent, refreshHistory, restoreCancelledSession, stateStore, submissionGate]);

  const startResearch = useCallback(
    (question: string) =>
      executeAction(
        () =>
          agentDeskRuntimeMode === "demo"
            ? createStartResearchAction(question, DEMO_RESEARCH_PARAMETERS)
            : adaptiveIntakeEnabled
              ? createPrepareResearchAction(question)
              : createStartResearchAction(question),
        question,
      ),
    [executeAction],
  );

  const submitIntake = useCallback(
    (surface: TrustedIntakeSurface, answers: IntakeAnswers) => {
      if (!isCurrentIntakeSurface(surface, stateStore.getSnapshot())) return Promise.resolve(false);
      return executeAction(
        () =>
          createSubmitIntakeAction({
            schemaVersion: "1.0",
            sessionId: surface.sessionId,
            proposalId: surface.proposalId,
            proposalVersion: surface.proposalVersion,
            answers,
          }),
        "Continue research with the clarified scope.",
      );
    },
    [executeAction, stateStore],
  );

  const startDirectResearch = useCallback(
    (question: string, parameters: StartResearchParameters) =>
      executeAction(
        () => createStartResearchAction(question, parameters),
        question,
      ),
    [executeAction],
  );

  const skipIntake = useCallback(
    (surface: TrustedIntakeSurface) => {
      if (!isCurrentIntakeSurface(surface, stateStore.getSnapshot())) return Promise.resolve(false);
      return executeAction(
        () => createSkipIntakeAction(surface.sessionId),
        "Skip clarification and continue with the proposed defaults.",
      );
    },
    [executeAction, stateStore],
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

  const rehydrateSession = useCallback(
    async (sessionId: string): Promise<boolean> => {
      setError(null);
      setPhase("connecting");
      setMessage("Loading saved research...");
      try {
        const detail = await getSessionHistory(sessionId);
        if (detail.session.threadId !== agent.threadId || !stateStore.replaceSnapshot(detail.state)) {
          throw new Error("The saved session does not belong to this browser thread.");
        }
        setIntakeSurface(null);
        setTimeline([]);
        setMessage("Saved research restored without rerunning specialists.");
        setPhase("idle");
        return true;
      } catch (historyError) {
        setError(userSafeAgUiError(historyError));
        setMessage("Saved research could not be restored.");
        setPhase("error");
        return false;
      }
    },
    [agent.threadId, stateStore],
  );

  const value = useMemo<AgentDeskRuntimeValue>(
    () => ({
      activeAction,
      cancelRun,
      challengeRecommendation,
      error,
      focusOnCriterion,
      history,
      intakeSurface,
      message,
      phase,
      researchDeeper,
      rehydrateSession,
      retryFailedAgent,
      skipIntake,
      startResearch,
      startDirectResearch,
      submitIntake,
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
      history,
      intakeSurface,
      message,
      phase,
      researchDeeper,
      rehydrateSession,
      retryFailedAgent,
      skipIntake,
      startResearch,
      startDirectResearch,
      submitIntake,
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
