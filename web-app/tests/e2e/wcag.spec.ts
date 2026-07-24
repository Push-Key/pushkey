import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { installRoutes } from "./support/mock-local-api";

/**
 * Automated WCAG 2.2 Level AA conformance scans for the critical journeys.
 *
 * `accessibility.spec.ts` asserts hand-authored semantics (names, roles,
 * disclosure state). This file is the complementary machine check: axe-core
 * runs the full WCAG 2.0/2.1/2.2 A + AA rule set over each critical journey
 * and fails on any violation.
 *
 * Scope note: axe-core cannot detect every AA success criterion (for example
 * 1.2.x media alternatives or 2.4.5 multiple ways). Those are covered by the
 * manual review recorded in `docs/accessibility-conformance.md`. A green run
 * here is necessary, not sufficient, for the documented conformance claim --
 * which is why the manual record exists alongside it.
 */

const WCAG_AA_TAGS = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
];

async function scan(page: Page) {
  return new AxeBuilder({ page }).withTags(WCAG_AA_TAGS).analyze();
}

function describeViolations(results: Awaited<ReturnType<typeof scan>>): string {
  return results.violations
    .map((violation) => {
      const nodes = violation.nodes.map((node) => `      ${node.target.join(" ")}`).join("\n");
      return `  [${violation.impact ?? "unknown"}] ${violation.id}: ${violation.help}\n${nodes}`;
    })
    .join("\n");
}

async function expectNoViolations(page: Page, journey: string) {
  const results = await scan(page);
  expect(
    results.violations,
    `WCAG 2.2 AA violations on the "${journey}" journey:\n${describeViolations(results)}`,
  ).toEqual([]);
}

test("locked vault journey has no WCAG 2.2 AA violations", async ({ page }) => {
  await installRoutes(page, true);
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await expect(page.getByLabel("Master password")).toBeVisible();

  await expectNoViolations(page, "locked vault / unlock");
});

test("recovery-code unlock journey has no WCAG 2.2 AA violations", async ({ page }) => {
  await installRoutes(page, true);
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Recovery Code" }).click();

  await expectNoViolations(page, "locked vault / recovery code");
});

test("dashboard journey has no WCAG 2.2 AA violations", async ({ page }) => {
  await installRoutes(page, false);
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await expect(page.getByRole("main")).toBeVisible();

  await expectNoViolations(page, "dashboard");
});

test("vault journey has no WCAG 2.2 AA violations", async ({ page }) => {
  await installRoutes(page, false);
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Vault" }).click();
  await expect(page.getByLabel("Search keys or providers")).toBeVisible();

  await expectNoViolations(page, "vault list");
});

test("add-key form has no WCAG 2.2 AA violations", async ({ page }) => {
  await installRoutes(page, false);
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Vault" }).click();
  await page.getByRole("button", { name: "Add key" }).click();
  await expect(page.getByText("New key")).toBeVisible();

  await expectNoViolations(page, "vault / add key");
});

test("health journey has no WCAG 2.2 AA violations", async ({ page }) => {
  await installRoutes(page, false);
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Health" }).click();
  await expect(page.getByLabel(/Staleness threshold/i)).toBeVisible();

  await expectNoViolations(page, "health");
});

test("projects journey has no WCAG 2.2 AA violations", async ({ page }) => {
  await installRoutes(page, false);
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Projects" }).click();
  await expect(page.getByRole("main")).toBeVisible();

  await expectNoViolations(page, "projects");
});

test("sidebar count badges have no WCAG 2.2 AA violations", async ({ page }) => {
  // The stale-key and overdue-rotation badges only render when their counts are
  // non-zero, so the other journeys never exercise them. Both are solid-fill
  // surfaces behind white text, which is exactly where contrast regresses.
  await installRoutes(page, false, { stale: 3, overdue: 2 });
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  const nav = page.getByRole("navigation", { name: "Primary navigation" });
  await expect(nav.getByText("stale keys", { exact: false }).first()).toBeAttached();
  await expect(nav.getByText("overdue rotations", { exact: false }).first()).toBeAttached();

  await expectNoViolations(page, "sidebar count badges");
});

test("settings journey has no WCAG 2.2 AA violations", async ({ page }) => {
  await installRoutes(page, false);
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page
    .getByRole("navigation", { name: "Primary navigation" })
    .getByRole("button", { name: "Open Settings" })
    .click();
  await expect(page.getByRole("main")).toBeVisible();

  await expectNoViolations(page, "settings");
});
