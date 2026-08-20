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

import { createCoordinatorAgent, runResearch } from "../agui/client";
import { useAgentDeskStateStore } from "../agui/store-react";

export type RuntimePhase = "idle" | "connecting" | "running" | "error";

interface AgentDeskRuntimeValue {
  cancelRun(): void;
  error: string | null;
  message: string;
  phase: RuntimePhase;
  startResearch(question: string): Promise<void>;
  threadId: string;
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
  const stateStore = useAgentDeskStateStore();

  const [phase, setPhase] = useState<RuntimePhase>("idle");
  const [message, setMessage] = useState("Ready for a new research question.");
  const [error, setError] = useState<string | null>(null);

  useEffect(
    () =>
      stateStore.subscribeRehydration((request) => {
        setError(`A malformed AG-UI ${request.cause} was rejected. ${request.message}`);
        setMessage("The last valid state is preserved; rehydration is required.");
        setPhase("error");
      }),
    [stateStore],
  );

  const startResearch = useCallback(async (question: string) => {
    setError(null);
    setPhase("connecting");
    setMessage("Connecting to the Coordinator...");
    try {
      await runResearch(agentRef.current!, question, {
        onDelta: stateStore.applyDelta,
        onRunning: () => setPhase("running"),
        onSnapshot: stateStore.replaceSnapshot,
        onMessage: setMessage,
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
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "AG-UI run failed.");
      setPhase("error");
    }
  }, [stateStore]);

  const cancelRun = useCallback(() => {
    agentRef.current?.abortRun();
  }, []);

  const value = useMemo<AgentDeskRuntimeValue>(
    () => ({
      cancelRun,
      error,
      message,
      phase,
      startResearch,
      threadId: agentRef.current!.threadId,
    }),
    [cancelRun, error, message, phase, startResearch],
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
