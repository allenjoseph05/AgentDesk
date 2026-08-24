import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./demo-e2e",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 30_000 },
  reporter: [
    ["line"],
    ["html", { open: "never", outputFolder: "demo-playwright-report" }],
  ],
  outputDir: "demo-test-results",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:5173",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
});
