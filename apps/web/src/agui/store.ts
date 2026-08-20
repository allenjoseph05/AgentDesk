import { z } from "zod";

import {
  INITIAL_AGENTDESK_STATE,
  parseAgentDeskViewState,
  type AgentDeskViewState,
} from "./state.ts";

const replaceOperationSchema = z
  .object({
    op: z.literal("replace"),
    path: z.string().min(2),
    value: z.unknown(),
  })
  .strict();

const stateDeltaSchema = z.array(replaceOperationSchema).min(1);

export interface RehydrationRequest {
  cause: "snapshot" | "delta";
  message: string;
  sessionId: string | null;
}

type StoreListener = () => void;
type RehydrationListener = (request: RehydrationRequest) => void;

export class AgentDeskStateStore {
  private state: AgentDeskViewState;
  private readonly listeners = new Set<StoreListener>();
  private readonly rehydrationListeners = new Set<RehydrationListener>();

  constructor(initialState: unknown = INITIAL_AGENTDESK_STATE) {
    this.state = immutableState(parseAgentDeskViewState(initialState));
  }

  readonly getSnapshot = (): AgentDeskViewState => this.state;

  readonly subscribe = (listener: StoreListener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly subscribeRehydration = (listener: RehydrationListener): (() => void) => {
    this.rehydrationListeners.add(listener);
    return () => this.rehydrationListeners.delete(listener);
  };

  readonly replaceSnapshot = (snapshot: unknown): boolean => {
    try {
      this.commit(parseAgentDeskViewState(snapshot));
      return true;
    } catch (error) {
      this.requestRehydration("snapshot", error);
      return false;
    }
  };

  readonly applyDelta = (delta: unknown): boolean => {
    try {
      const operations = stateDeltaSchema.parse(delta);
      let candidate: Record<string, unknown> = structuredClone(this.state);
      for (const operation of operations) {
        if (!Object.hasOwn(operation, "value")) {
          throw new Error("State replace operation requires a value.");
        }
        const key = topLevelStateKey(operation.path);
        if (!Object.hasOwn(candidate, key)) {
          throw new Error(`State patch targets unknown field: ${key}.`);
        }
        candidate = { ...candidate, [key]: structuredClone(operation.value) };
      }
      this.commit(parseAgentDeskViewState(candidate));
      return true;
    } catch (error) {
      this.requestRehydration("delta", error);
      return false;
    }
  };

  private commit(state: AgentDeskViewState): void {
    this.state = immutableState(state);
    for (const listener of this.listeners) {
      listener();
    }
  }

  private requestRehydration(
    cause: RehydrationRequest["cause"],
    error: unknown,
  ): void {
    const request: RehydrationRequest = {
      cause,
      message: error instanceof Error ? error.message : "Unknown AG-UI state error.",
      sessionId: this.state.sessionId,
    };
    for (const listener of this.rehydrationListeners) {
      listener(request);
    }
  }
}

function topLevelStateKey(path: string): string {
  if (!path.startsWith("/") || path.slice(1).includes("/")) {
    throw new Error("State patches must replace one top-level field.");
  }
  const encoded = path.slice(1);
  if (/~(?![01])/u.test(encoded)) {
    throw new Error("State patch contains an invalid JSON Pointer escape.");
  }
  return encoded.replaceAll("~1", "/").replaceAll("~0", "~");
}

function immutableState(state: AgentDeskViewState): AgentDeskViewState {
  return deepFreeze(structuredClone(state));
}

function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) {
      deepFreeze(child);
    }
  }
  return value;
}
