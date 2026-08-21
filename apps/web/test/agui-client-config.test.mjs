import assert from "node:assert/strict";
import test from "node:test";

import {
  BROWSER_THREAD_STORAGE_KEY,
  createAuthenticatedFetch,
  getOrCreateBrowserThreadId,
  resolveAgUiEndpoint,
  userSafeAgUiError,
} from "../src/agui/client-config.ts";

test("browser endpoint configuration accepts relative and HTTP(S) targets only", () => {
  assert.equal(resolveAgUiEndpoint({}), "/ag-ui");
  assert.equal(
    resolveAgUiEndpoint({ VITE_AGENTDESK_AG_UI_ENDPOINT: " /coordinator/ag-ui " }),
    "/coordinator/ag-ui",
  );
  assert.equal(
    resolveAgUiEndpoint({ VITE_AGENTDESK_AG_UI_ENDPOINT: "https://api.example/ag-ui" }),
    "https://api.example/ag-ui",
  );
  assert.throws(
    () => resolveAgUiEndpoint({ VITE_AGENTDESK_AG_UI_ENDPOINT: "javascript:alert(1)" }),
    /HTTP or HTTPS/u,
  );
  assert.throws(
    () => resolveAgUiEndpoint({ VITE_AGENTDESK_AG_UI_ENDPOINT: "coordinator" }),
    /relative or an HTTP/u,
  );
});

test("browser thread identity survives client reconstruction with a storage fallback", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  let created = 0;
  const createId = () => `thread-${++created}`;

  assert.equal(getOrCreateBrowserThreadId(storage, createId), "thread-1");
  assert.equal(getOrCreateBrowserThreadId(storage, createId), "thread-1");
  assert.equal(values.get(BROWSER_THREAD_STORAGE_KEY), "thread-1");
  assert.equal(getOrCreateBrowserThreadId(null, createId), "thread-2");

  const blockedStorage = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
  };
  assert.equal(getOrCreateBrowserThreadId(blockedStorage, createId), "thread-3");
});

test("authentication hook resolves per request and cannot inject malformed headers", async () => {
  const requests = [];
  let tokenVersion = 0;
  const authenticatedFetch = createAuthenticatedFetch(
    async (url, init) => {
      requests.push({ url, init });
      return new Response(null, { status: 204 });
    },
    async () => ({ Authorization: `Bearer token-${++tokenVersion}` }),
  );

  await authenticatedFetch("/ag-ui", { headers: { "content-type": "application/json" } });
  await authenticatedFetch("/ag-ui", { headers: { "content-type": "application/json" } });
  assert.equal(new Headers(requests[0].init.headers).get("authorization"), "Bearer token-1");
  assert.equal(new Headers(requests[1].init.headers).get("authorization"), "Bearer token-2");
  assert.equal(new Headers(requests[1].init.headers).get("content-type"), "application/json");

  const invalidFetch = createAuthenticatedFetch(
    async () => { throw new Error("must not fetch"); },
    () => ({ Authorization: "Bearer valid\r\ninjected: true" }),
  );
  await assert.rejects(invalidFetch("/ag-ui", {}), /invalid header/u);
});

test("transport and server failures map to bounded user-safe messages", () => {
  assert.equal(
    userSafeAgUiError(new TypeError("Failed to fetch https://secret.internal/ag-ui")),
    "The Coordinator is temporarily unavailable. Check the connection and retry.",
  );
  assert.match(userSafeAgUiError(new Error("HTTP 401 from provider")), /authenticated/u);
  assert.match(userSafeAgUiError(new Error("429 too many requests")), /busy/u);
  assert.doesNotMatch(
    userSafeAgUiError(new Error("provider token sk-secret at C:\\private\\server.py")),
    /sk-secret|server\.py/u,
  );
});
