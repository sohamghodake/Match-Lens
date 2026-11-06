import path from "node:path";

import { expect, test } from "@playwright/test";

// The generated sample resume from backend/eval/samples (fictional person).
const SAMPLE = path.join(__dirname, "..", "..", "backend", "eval", "samples", "alex_chen_backend.pdf");

test("upload a resume, see matches, check ATS fit", async ({ page }) => {
  await page.goto("/");
  await page.setInputFiles("#resume-file", SAMPLE);

  // Parsed profile (with an LLM, or the rule-based fallback when there is none).
  await page.waitForURL(/\/resume\/[0-9a-f-]{36}$/, { timeout: 90_000 });
  const main = page.getByRole("main");
  await expect(main.getByText("Parsed profile")).toBeVisible();
  await expect(main.getByRole("listitem").filter({ hasText: "PostgreSQL" }).first()).toBeVisible();

  // Matches: ranked cards, each crediting its source.
  await main.getByRole("link", { name: "Find matching jobs →" }).click();
  await page.waitForURL(/\/matches$/);
  const cards = page.getByRole("main").locator("ol > li");
  await expect(cards.first()).toBeVisible({ timeout: 90_000 });
  expect(await cards.count()).toBeGreaterThan(0);
  await expect(cards.first().getByRole("link", { name: /View job on/ })).toBeVisible();

  // ATS check for the top match: a score and a part-by-part breakdown.
  await cards.first().getByRole("link", { name: "Check ATS fit" }).click();
  await page.waitForURL(/\/ats\?job=\d+/);
  const ats = page.getByRole("main");
  await expect(ats.getByText(/Strong match|Fair match|Needs work/)).toBeVisible({ timeout: 60_000 });
  await expect(ats.getByText("Keyword coverage")).toBeVisible();
  await expect(ats.getByText("Seniority and experience")).toBeVisible();
});
