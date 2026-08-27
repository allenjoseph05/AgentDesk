import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  createProductionServer,
  resolveCoordinatorUrl,
} from "../production-server.mjs";

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new Error("Expected a TCP server address.");
  }
  return `http://127.0.0.1:${address.port}`;
}

async function close(server) {
  await new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

test("production server serves the SPA and streams Coordinator responses", async () => {
  const root = await mkdtemp(join(tmpdir(), "agentdesk-web-"));
  await mkdir(join(root, "assets"));
  await writeFile(join(root, "index.html"), "<main>AgentDesk production</main>", "utf8");
  await writeFile(join(root, "assets", "app.js"), "export const ready = true;", "utf8");

  let capturedPath = "";
  let capturedBody = "";
  const coordinator = createServer((request, response) => {
    capturedPath = request.url ?? "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => {
      capturedBody += chunk;
    });
    request.on("end", () => {
      response.writeHead(200, { "content-type": "text/event-stream" });
      response.end('data: {"type":"RUN_FINISHED"}\n\n');
    });
  });
  const coordinatorOrigin = await listen(coordinator);
  const web = createProductionServer({
    coordinatorUrl: new URL(coordinatorOrigin),
    root,
  });
  const webOrigin = await listen(web);

  try {
    const health = await fetch(`${webOrigin}/healthz`);
    assert.equal(health.status, 200);
    assert.deepEqual(await health.json(), { status: "ok" });

    const asset = await fetch(`${webOrigin}/assets/app.js`);
    assert.equal(asset.status, 200);
    assert.match(asset.headers.get("cache-control") ?? "", /immutable/u);
    assert.equal(await asset.text(), "export const ready = true;");

    const fallback = await fetch(`${webOrigin}/research/session-1`);
    assert.equal(fallback.status, 200);
    assert.match(await fallback.text(), /AgentDesk production/u);

    const stream = await fetch(`${webOrigin}/ag-ui?source=browser`, {
      body: '{"threadId":"thread-1"}',
      headers: { "content-type": "application/json" },
      method: "POST",
    });
    assert.equal(stream.status, 200);
    assert.equal(stream.headers.get("content-type"), "text/event-stream");
    assert.match(await stream.text(), /RUN_FINISHED/u);
    assert.equal(capturedPath, "/ag-ui?source=browser");
    assert.equal(capturedBody, '{"threadId":"thread-1"}');
  } finally {
    await close(web);
    await close(coordinator);
    await rm(root, { force: true, recursive: true });
  }
});

test("Coordinator endpoint accepts a private hostport and rejects unsafe URLs", () => {
  assert.equal(
    resolveCoordinatorUrl({ AGENTDESK_COORDINATOR_HOSTPORT: "coordinator:10000" }).href,
    "http://coordinator:10000/",
  );
  assert.throws(
    () => resolveCoordinatorUrl({ AGENTDESK_COORDINATOR_URL: "ftp://coordinator/file" }),
    /HTTP or HTTPS/u,
  );
  assert.throws(
    () => resolveCoordinatorUrl({ AGENTDESK_COORDINATOR_URL: "https://token@coordinator" }),
    /cannot contain credentials/u,
  );
});
