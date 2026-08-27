import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { request as requestHttp } from "node:http";
import { request as requestHttps } from "node:https";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const DEFAULT_ROOT = fileURLToPath(new URL("./dist", import.meta.url));
const CONTENT_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".webp", "image/webp"],
]);
const PROXY_PATHS = ["/ag-ui", "/api/sessions"];

export function resolveCoordinatorUrl(environment = process.env) {
  const configured = environment.AGENTDESK_COORDINATOR_URL?.trim();
  const hostport = environment.AGENTDESK_COORDINATOR_HOSTPORT?.trim();
  const value = configured || (hostport ? `http://${hostport}` : "");
  if (!value) {
    throw new Error(
      "AGENTDESK_COORDINATOR_URL or AGENTDESK_COORDINATOR_HOSTPORT is required.",
    );
  }
  const url = new URL(value);
  if (!new Set(["http:", "https:"]).has(url.protocol)) {
    throw new Error("The Coordinator URL must use HTTP or HTTPS.");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("The Coordinator URL cannot contain credentials, query, or fragment.");
  }
  return url;
}

export function createProductionServer({
  coordinatorUrl = resolveCoordinatorUrl(),
  root = DEFAULT_ROOT,
} = {}) {
  const staticRoot = resolve(root);
  return createServer(async (request, response) => {
    const requestUrl = new URL(request.url ?? "/", "http://agentdesk.invalid");
    if (requestUrl.pathname === "/healthz") {
      send(response, 200, "application/json; charset=utf-8", '{"status":"ok"}\n');
      return;
    }
    if (PROXY_PATHS.some((path) => requestUrl.pathname === path || requestUrl.pathname.startsWith(`${path}/`))) {
      proxyRequest(request, response, coordinatorUrl);
      return;
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      send(response, 404, "text/plain; charset=utf-8", "Not found\n");
      return;
    }
    try {
      await serveStatic(requestUrl.pathname, request.method, response, staticRoot);
    } catch {
      send(response, 500, "text/plain; charset=utf-8", "Static asset unavailable\n");
    }
  });
}

async function serveStatic(pathname, method, response, staticRoot) {
  let decodedPath;
  try {
    decodedPath = decodeURIComponent(pathname);
  } catch {
    send(response, 400, "text/plain; charset=utf-8", "Invalid path\n");
    return;
  }
  const requested = decodedPath === "/" ? "index.html" : decodedPath.replace(/^\/+/, "");
  let filePath = resolve(staticRoot, requested);
  if (filePath !== staticRoot && !filePath.startsWith(`${staticRoot}${sep}`)) {
    send(response, 403, "text/plain; charset=utf-8", "Forbidden\n");
    return;
  }
  try {
    const metadata = await stat(filePath);
    if (!metadata.isFile()) {
      throw new Error("Not a file");
    }
  } catch {
    filePath = resolve(staticRoot, "index.html");
    await stat(filePath);
  }
  const contentType = CONTENT_TYPES.get(extname(filePath)) ?? "application/octet-stream";
  response.writeHead(200, {
    "cache-control": filePath.endsWith("index.html")
      ? "no-cache"
      : "public, max-age=31536000, immutable",
    "content-type": contentType,
  });
  if (method === "HEAD") {
    response.end();
    return;
  }
  createReadStream(filePath).pipe(response);
}

function proxyRequest(request, response, coordinatorUrl) {
  const target = new URL(request.url ?? "/", coordinatorUrl);
  const requestFunction = target.protocol === "https:" ? requestHttps : requestHttp;
  const headers = { ...request.headers, host: target.host };
  delete headers.connection;
  const upstream = requestFunction(
    target,
    { headers, method: request.method },
    (upstreamResponse) => {
      const responseHeaders = { ...upstreamResponse.headers };
      delete responseHeaders.connection;
      response.writeHead(upstreamResponse.statusCode ?? 502, responseHeaders);
      upstreamResponse.pipe(response);
    },
  );
  upstream.on("error", () => {
    if (!response.headersSent) {
      send(response, 502, "application/json; charset=utf-8", '{"error":"Coordinator unavailable"}\n');
    } else {
      response.destroy();
    }
  });
  request.on("aborted", () => upstream.destroy());
  response.on("close", () => {
    if (!response.writableEnded) {
      upstream.destroy();
    }
  });
  request.pipe(upstream);
}

function send(response, status, contentType, body) {
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-type": contentType,
  });
  response.end(body);
}

function start() {
  const port = Number.parseInt(process.env.PORT ?? "10000", 10);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("PORT must be an integer between 1 and 65535.");
  }
  const server = createProductionServer();
  server.listen(port, "0.0.0.0", () => {
    process.stdout.write(`AgentDesk web listening on ${port}\n`);
  });
}

const entrypoint = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === entrypoint) {
  start();
}
