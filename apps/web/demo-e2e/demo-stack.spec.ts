import { expect, test } from "@playwright/test";

const QUESTION = "Should the product use PostgreSQL or MongoDB?";
const CHALLENGE = "What if schema flexibility matters more than relational integrity?";

test("fixture demo completes the real multi-agent flow with predictable UI states", async ({
  page,
}) => {
  await page.goto("/");

  const codespacesWarning = page.getByRole("heading", {
    name: /access a development port/u,
  });
  if (await codespacesWarning.isVisible()) {
    await page.getByRole("button", { name: "Continue", exact: true }).click();
  }

  await expect(page.getByText("Fixture demo", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/fixed local fixtures and predictable stage timing/u),
  ).toBeVisible();
  const question = page.getByRole("textbox", { name: "Research question", exact: true });
  await expect(question).toHaveValue(QUESTION);
  await expect(question).toHaveAttribute("readonly", "");

  await page.getByRole("button", { name: "Start research" }).click();

  await expect(page.getByRole("heading", { name: "PostgreSQL", exact: true })).toBeVisible();
  await expect(page.getByText("PostgreSQL integrity fixture", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Relational integrity outweighs metadata flexibility.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verification" })).toBeVisible();
  await expect(page.getByText("Complete", { exact: true }).first()).toBeVisible();

  await page.getByLabel("Optional challenge").fill(CHALLENGE);
  await page.getByRole("button", { name: "Test counterargument" }).click();
  await expect(
    page.getByRole("heading", { name: "Strongest alternative: MongoDB" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "MongoDB becomes the stronger choice when flexible document structures outweigh relational integrity.",
    ),
  ).toBeVisible();
});
