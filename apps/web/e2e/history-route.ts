import type { Page } from "@playwright/test";

export async function installEmptyHistoryRoute(page: Page): Promise<void> {
  await page.route("**/api/sessions**", async (route) => {
    await route.fulfill({
      body: JSON.stringify({ sessions: [] }),
      contentType: "application/json",
      status: 200,
    });
  });
}
