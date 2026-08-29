import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../../..", import.meta.url));
const fixturePython = fileURLToPath(
  new URL(
    process.platform === "win32" ? "../../../.venv/Scripts/python.exe" : "../../../.venv/bin/python",
    import.meta.url,
  ),
);
const fixtureLauncher = fileURLToPath(
  new URL("../../../scripts/start_adaptive_intake_fixture_stack.py", import.meta.url),
);

export default async function startAdaptiveFixtureStack() {
  const stack = spawn(fixturePython, [fixtureLauncher, "--backend-only"], {
    cwd: repositoryRoot,
    env: process.env,
    stdio: "inherit",
    windowsHide: true,
  });
  try {
    await waitForStack(stack);
  } catch (error) {
    stopStack(stack);
    throw error;
  }
  return () => stopStack(stack);
}

async function waitForStack(stack: ChildProcess): Promise<void> {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (stack.exitCode !== null) {
      throw new Error(`Adaptive fixture stack stopped with exit code ${stack.exitCode}.`);
    }
    try {
      const response = await fetch("http://127.0.0.1:8180/ready");
      if (response.ok) return;
    } catch {
      // The local processes are still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Adaptive fixture stack did not become ready within 60 seconds.");
}

function stopStack(stack: ChildProcess): void {
  if (stack.pid === undefined || stack.exitCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(stack.pid), "/t", "/f"], {
      stdio: "ignore",
      windowsHide: true,
    });
    return;
  }
  stack.kill("SIGTERM");
}
