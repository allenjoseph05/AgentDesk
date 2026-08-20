import {
  createContext,
  type ReactNode,
  useContext,
  useRef,
  useSyncExternalStore,
} from "react";

import type { AgentDeskViewState } from "./state";
import { AgentDeskStateStore } from "./store";

interface AgentDeskStateProviderProps {
  children: ReactNode;
  store?: AgentDeskStateStore;
}

const AgentDeskStateContext = createContext<AgentDeskStateStore | null>(null);

export function AgentDeskStateProvider({
  children,
  store: suppliedStore,
}: AgentDeskStateProviderProps) {
  const storeRef = useRef<AgentDeskStateStore | null>(null);
  storeRef.current ??= suppliedStore ?? new AgentDeskStateStore();
  return (
    <AgentDeskStateContext.Provider value={storeRef.current}>
      {children}
    </AgentDeskStateContext.Provider>
  );
}

export function useAgentDeskStateStore(): AgentDeskStateStore {
  const store = useContext(AgentDeskStateContext);
  if (store === null) {
    throw new Error("AgentDesk state hooks require AgentDeskStateProvider.");
  }
  return store;
}

export function useAgentDeskSelector<Selection>(
  selector: (state: AgentDeskViewState) => Selection,
): Selection {
  const store = useAgentDeskStateStore();
  const state = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot,
  );
  return selector(state);
}
