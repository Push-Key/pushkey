import { expect, test, type Page } from "@playwright/test";

type RouteState = {
  locked: boolean;
};

async function installShellRoutes(page: Page, state: RouteState) {
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
        locked: state.locked,
        has_vault: true,
        vault_schema: 3,
        key_count: 2,
        autolock_seconds: 30,
        idle_seconds: 0,
        auth_method: "cookie_session",
        can_write: !state.locked,
      }),
    }),
  );

  await page.route("**/api/health**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        total: 2,
        healthy: [
          { name: "OPENAI_API_KEY", provider: "openai", env: "dev", age_days: 2, status: "healthy" },
        ],
        stale: [
          { name: "STRIPE_KEY", provider: "stripe", env: "prod", age_days: 21, status: "warning" },
        ],
        unknown_provider: [],
        backup_missing: ["STRIPE_KEY"],
        score: 88,
        threshold_days: 90,
      }),
    }),
  );

  await page.route("**/api/forecast**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        upcoming: [
          {
            name: "STRIPE_KEY",
            provider: "stripe",
            env: "prod",
            due_date: "2026-08-10",
            days_left: 20,
            overdue: false,
            has_backup: false,
          },
        ],
        count: 1,
        window_days: 30,
      }),
    }),
  );

  await page.route("**/api/keys", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        keys: [
          {
            name: "OPENAI_API_KEY",
            env: "dev",
            rotated: "2026-07-20",
            added: "2026-07-19",
            provider: "openai",
            dual_rotation: true,
            has_backup: true,
            history_count: 1,
            team_role: null,
            masked: "sk-••••••••••••",
          },
        ],
        count: 1,
      }),
    }),
  );

  await page.route("**/api/projects", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        projects: [
          { path: "/workspace/app", name: "app", keys: ["OPENAI_API_KEY"], created: "2026-07-19" },
        ],
        count: 1,
      }),
    }),
  );

  await page.route("**/api/agents", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ tokens: [{ id: "agent-1", name: "Editor", scopes: ["read"] }] }),
    }),
  );

  await page.route("**/api/audit", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        events: [{ timestamp: "2026-07-21T12:00:00Z", message: "loaded" }],
        count: 1,
      }),
    }),
  );

  await page.route("**/api/lock", (route) => {
    state.locked = true;
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ locked: true }),
    });
  });
}

test("loads the unlocked shell and responds to lock actions", async ({ page }) => {
  const state = { locked: false };
  await installShellRoutes(page, state);

  await page.goto("/#t=launch-token", { waitUntil: "commit" });

  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Dashboard" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Lock vault" })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Open Settings" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  await page.getByRole("button", { name: "Lock vault" }).click();

  await expect(page.getByText("Offline or locked: unlock locally to load vault data and write changes.")).toBeVisible();
  await expect(page.getByLabel("Master password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Master Password" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Recovery Code" })).toBeVisible();
});

test("shows the locked session controls with accessible labels", async ({ page }) => {
  const state = { locked: true };
  await installShellRoutes(page, state);

  await page.goto("/#t=launch-token", { waitUntil: "commit" });

  await expect(page.getByText("Offline or locked: unlock locally to load vault data and write changes.")).toBeVisible();
  await expect(page.getByLabel("Master password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Master Password" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Recovery Code" })).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByRole("button", { name: "Recovery Code" })).toBeVisible();

  await page.getByRole("button", { name: "Recovery Code" }).click();
  await expect(page.getByText("Recovery unlock is read-only")).toBeVisible();
});
