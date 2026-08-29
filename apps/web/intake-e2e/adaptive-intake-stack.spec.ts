import { expect, type Page, test } from "@playwright/test";

const QUESTION = "Should the product use PostgreSQL or MongoDB?";

async function openAdaptiveFixture(page: Page) {
  await page.goto("/");
  await expect(page.getByText("Adaptive fixture", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Research question" })).toHaveValue(QUESTION);
}

async function openIntake(page: Page) {
  await page.getByRole("button", { name: "Start research" }).click();
  await expect(page.getByRole("heading", { name: "Clarify your decision" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Primary workload" })).toBeVisible();
}

async function expectCompletedDecision(page: Page) {
  await expect(page.getByRole("heading", { name: "PostgreSQL", exact: true })).toBeVisible();
  await expect(page.getByText("PostgreSQL integrity fixture", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Relational integrity outweighs metadata flexibility.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verification" })).toBeVisible();
  await expect(page.getByText("Complete", { exact: true }).first()).toBeVisible();
}

test("submit crosses ADK/A2A/A2UI/AG-UI, rejects replay, and rehydrates from history", async ({
  page,
}) => {
  const agUiBodies: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/ag-ui") {
      const body = request.postData();
      if (body !== null) agUiBodies.push(body);
    }
  });

  await openAdaptiveFixture(page);
  await openIntake(page);
  await page.getByLabel("Preserve transactional integrity").check();
  await page.getByLabel("Schema flexibility").check();
  await page.getByRole("button", { name: "Continue with these answers" }).click();
  await expectCompletedDecision(page);

  expect(agUiBodies).toHaveLength(2);
  const replay = await page.request.post("/ag-ui", {
    data: JSON.parse(agUiBodies[1] ?? "{}"),
    headers: { accept: "text/event-stream" },
  });
  expect(replay.status()).toBe(200);
  await expect.poll(async () => replay.text()).toContain("duplicate_action");

  await expect(page.getByRole("navigation", { name: "Research history" }).getByRole("button"))
    .toHaveCount(1);
  await page.reload();
  const savedSession = page
    .getByRole("navigation", { name: "Research history" })
    .getByRole("button", { name: new RegExp(QUESTION, "u") });
  await expect(savedSession).toBeVisible();
  await savedSession.click();
  await expectCompletedDecision(page);
  await expect(page.getByText("Saved research restored without rerunning specialists.")).toBeVisible();
  expect(agUiBodies).toHaveLength(2);
});

test("skip uses trusted defaults and completes the existing specialist path", async ({ page }) => {
  await openAdaptiveFixture(page);
  await openIntake(page);
  await page.getByRole("button", { name: "Skip clarification" }).click();
  await expectCompletedDecision(page);
});

test("browser cancellation reaches the active scoping run and permits a fresh run", async ({
  page,
}) => {
  await openAdaptiveFixture(page);
  await page.getByRole("button", { name: "Start research" }).click();
  await page.getByRole("button", { name: "Cancel active run" }).click();
  await expect(page.getByText("Cancelled", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Research run cancelled.", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Start research" }).click();
  await expect(page.getByRole("heading", { name: "Clarify your decision" })).toBeVisible();
});
