import type { HttpAgentFetchFn } from "@ag-ui/client";

export const DEFAULT_AG_UI_ENDPOINT = "/ag-ui";
export const BROWSER_THREAD_STORAGE_KEY = "agentdesk.agui.thread-id";

export interface BrowserClientEnvironment {
  VITE_AGENTDESK_AG_UI_ENDPOINT?: unknown;
}

export interface BrowserStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export type AuthenticationHeaderProvider = () =>
  | Promise<Readonly<Record<string, string>>>
  | Readonly<Record<string, string>>;

export function resolveAgUiEndpoint(environment: BrowserClientEnvironment): string {
  const configured = environment.VITE_AGENTDESK_AG_UI_ENDPOINT;
  if (configured === undefined || configured === null || configured === "") {
    return DEFAULT_AG_UI_ENDPOINT;
  }
  if (typeof configured !== "string") {
    throw new Error("VITE_AGENTDESK_AG_UI_ENDPOINT must be a URL string.");
  }
  const endpoint = configured.trim();
  if (endpoint.startsWith("/") && !endpoint.startsWith("//")) {
    return endpoint;
  }
  let parsed: URL;
  try {
    parsed = new URL(endpoint);
  } catch {
    throw new Error("VITE_AGENTDESK_AG_UI_ENDPOINT must be relative or an HTTP(S) URL.");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("VITE_AGENTDESK_AG_UI_ENDPOINT must use HTTP or HTTPS.");
  }
  return parsed.toString();
}

export function getOrCreateBrowserThreadId(
  storage: BrowserStorage | null,
  createId: () => string = () => crypto.randomUUID(),
): string {
  if (storage !== null) {
    try {
      const existing = storage.getItem(BROWSER_THREAD_STORAGE_KEY)?.trim();
      if (existing) {
        return existing;
      }
      const created = createId();
      storage.setItem(BROWSER_THREAD_STORAGE_KEY, created);
      return created;
    } catch {
      // Storage can be disabled by browser privacy settings; continuity then lasts for this mount.
    }
  }
  return createId();
}

export function createAuthenticatedFetch(
  baseFetch: HttpAgentFetchFn,
  getAuthenticationHeaders?: AuthenticationHeaderProvider,
): HttpAgentFetchFn {
  if (getAuthenticationHeaders === undefined) {
    return baseFetch;
  }
  return async (url, requestInit) => {
    const authenticationHeaders = await getAuthenticationHeaders();
    const headers = new Headers(requestInit.headers);
    for (const [name, value] of Object.entries(authenticationHeaders)) {
      if (!isSafeHeaderName(name) || /[\r\n]/u.test(value)) {
        throw new Error("Authentication hook returned an invalid header.");
      }
      headers.set(name, value);
    }
    return baseFetch(url, { ...requestInit, headers });
  };
}

export function userSafeAgUiError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (/abort|cancel/iu.test(message)) {
    return "The active run was cancelled.";
  }
  if (/\b401\b|unauthori[sz]ed|authentication/iu.test(message)) {
    return "Your session could not be authenticated. Sign in again and retry.";
  }
  if (/\b403\b|forbidden/iu.test(message)) {
    return "You do not have access to this research session.";
  }
  if (/\b429\b|rate.?limit|too many requests/iu.test(message)) {
    return "The Coordinator is busy. Wait a moment and retry.";
  }
  if (/failed to fetch|network|econn|\b5\d\d\b|service unavailable/iu.test(message)) {
    return "The Coordinator is temporarily unavailable. Check the connection and retry.";
  }
  if (
    /^(A research question|A user-facing action message|Invalid AgentDesk action|Unsupported AG-UI)/u.test(
      message,
    )
  ) {
    return message;
  }
  return "The Coordinator could not complete this run. Retry or start a new research session.";
}

function isSafeHeaderName(value: string): boolean {
  return /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/u.test(value);
}
