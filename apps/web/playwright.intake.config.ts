import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./intake-e2e",
  globalSetup: "./intake-e2e/global-setup.ts",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 45_000 },
  reporter: [
    ["line"],
    ["html", { open: "never", outputFolder: "../../.tmp/intake-playwright-report" }],
  ],
  outputDir: "../../.tmp/intake-test-results",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:5183",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: "node ../../node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5183 --strictPort",
    env: {
      AGENTDESK_COORDINATOR_URL: "http://127.0.0.1:8180",
      VITE_AGENTDESK_RUNTIME_MODE: "adaptive-demo",
    },
    url: "http://127.0.0.1:5183",
    reuseExistingServer: false,
    stdout: "pipe",
    stderr: "pipe",
    timeout: 60_000,
  },
});
