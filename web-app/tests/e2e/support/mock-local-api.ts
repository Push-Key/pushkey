import type { Page } from "@playwright/test";

export type MockOptions = {
  /** Number of stale keys, which renders the sidebar health count badge. */
  stale?: number;
  /** Number of overdue rotations, which renders the forecast count badge. */
  overdue?: number;
};

function staleKeys(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    name: `STALE_KEY_${index + 1}`,
    provider: "openai",
    age_days: 200,
  }));
}

function overdueRotations(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    name: `OVERDUE_KEY_${index + 1}`,
    provider: "openai",
    due_in_days: -5,
    overdue: true,
  }));
}

/**
 * Stub the local API surface the app calls on boot.
 *
 * Shared by the accessibility specs so the named-control checks and the
 * automated WCAG scans exercise exactly the same rendered shell.
 */
export async function installRoutes(page: Page, locked: boolean, options: MockOptions = {}) {
  const stale = staleKeys(options.stale ?? 0);
  const overdue = overdueRotations(options.overdue ?? 0);
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

  await page.route("**/api/health**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        total: stale.length,
        healthy: [],
        stale,
        unknown_provider: [],
        backup_missing: [],
        score: stale.length ? 40 : 100,
        threshold_days: 90,
      }),
    }),
  );

  await page.route("**/api/forecast**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        upcoming: overdue,
        count: overdue.length,
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
