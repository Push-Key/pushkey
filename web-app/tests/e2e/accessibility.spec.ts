import { expect, test, type Page } from "@playwright/test";

async function installRoutes(page: Page, locked: boolean) {
  await page.route("**/api/bootstrap", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ token: "session-token" }),
    }),
  );

  await page.route("**/api/status", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        locked,
        has_vault: true,
        vault_schema: 3,
        key_count: 2,
        autolock_seconds: 30,
        idle_seconds: 0,
        auth_method: "cookie_session",
        can_write: !locked,
      }),
    }),
  );

  await page.route("**/api/health", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        total: 0,
        healthy: [],
        stale: [],
        unknown_provider: [],
        backup_missing: [],
        score: 100,
        threshold_days: 90,
      }),
    }),
  );

  await page.route("**/api/forecast", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        upcoming: [],
        count: 0,
        window_days: 30,
      }),
    }),
  );

  await page.route("**/api/keys", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ keys: [], count: 0 }),
    }),
  );

  await page.route("**/api/projects", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ projects: [], count: 0 }),
    }),
  );

  await page.route("**/api/agents", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ tokens: [] }),
    }),
  );

  await page.route("**/api/audit", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ events: [], count: 0 }),
    }),
  );

  await page.route("**/api/lock", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ locked: true }),
    }),
  );
}

async function collectUnnamedInteractiveControls(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const interactiveSelectors = [
      "button",
      "[role='button']",
      "a[href]",
      "[role='link']",
      "input",
      "textarea",
      "select",
      "[role='checkbox']",
      "[role='combobox']",
      "[role='menuitem']",
      "[role='menuitemcheckbox']",
      "[role='menuitemradio']",
      "[role='radio']",
      "[role='switch']",
      "[role='tab']",
    ].join(",");

    const describe = (el: Element) => {
      const id = el.id ? `#${el.id}` : "";
      const className = typeof (el as HTMLElement).className === "string" ? String((el as HTMLElement).className).trim().replace(/\s+/g, ".") : "";
      return `${el.tagName.toLowerCase()}${id}${className ? `.${className}` : ""}`;
    };

    const getAssociatedLabel = (el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement) => {
      const labels = Array.from(el.labels ?? [])
        .map((label) => label.textContent?.replace(/\s+/g, " ").trim() ?? "")
        .filter(Boolean);
      if (labels.length) return labels.join(" ");
      const ariaLabelledBy = el.getAttribute("aria-labelledby");
      if (ariaLabelledBy) {
        const label = ariaLabelledBy
          .split(/\s+/)
          .map((id) => document.getElementById(id)?.textContent?.replace(/\s+/g, " ").trim() ?? "")
          .filter(Boolean)
          .join(" ")
          .trim();
        if (label) return label;
      }
      return "";
    };

    const controls = Array.from(document.querySelectorAll(interactiveSelectors))
      .filter((el) => el instanceof HTMLElement)
      .filter((el) => {
        const style = window.getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && el.getClientRects().length > 0;
      });

    const issues: string[] = [];
    for (const el of controls) {
      const ariaLabel = el.getAttribute("aria-label")?.replace(/\s+/g, " ").trim() ?? "";
      const title = el.getAttribute("title")?.replace(/\s+/g, " ").trim() ?? "";
      const text = el.textContent?.replace(/\s+/g, " ").trim() ?? "";

      let label = ariaLabel || title || text;
      if ((el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) && !label) {
        label = getAssociatedLabel(el);
        if (!label) label = el.placeholder?.replace(/\s+/g, " ").trim() ?? "";
      }

      if (!label) {
        issues.push(describe(el));
      }
    }

    return issues;
  });
}

test("unlocked shell keeps critical controls named in the accessibility tree", async ({ page }) => {
  await installRoutes(page, false);

  await page.goto("/#t=launch-token");

  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("button", { name: "Lock vault" })).toBeVisible();

  const unnamedControls = await collectUnnamedInteractiveControls(page);
  expect(unnamedControls).toEqual([]);
});

test("locked shell keeps login controls named in the accessibility tree", async ({ page }) => {
  await installRoutes(page, true);

  await page.goto("/#t=launch-token");

  await expect(page.getByLabel("Master password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Master Password" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Recovery Code" })).toBeVisible();

  const unnamedControls = await collectUnnamedInteractiveControls(page);
  expect(unnamedControls).toEqual([]);
});
