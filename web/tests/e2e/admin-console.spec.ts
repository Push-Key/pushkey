import { expect, test } from "@playwright/test"

const api = "http://127.0.0.1:8123"
const license = {
  key: "PRO-ALPHA-ADMIN-0001-CHECK",
  tier: "pro",
  email: "alpha@example.com",
  platform: "windows",
  activated: "2026-07-21T10:00:00",
  last_heartbeat: "2026-07-21T10:30:00",
  status: "active",
  notes: "alpha admin journey",
  name: "Alpha Buyer",
  company: "Acme",
  source: "Direct",
  follow_up_date: "2026-07-28",
  expires_at: "2026-08-21T10:00:00",
  stage: "trial",
  sent_invite: false,
}

test.beforeEach(async ({ page }) => {
  await page.route(`${api}/api/admin/auth/login`, route =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        csrf_token: "csrf",
        admin: { id: "owner", email: "admin@example.com", role: "owner" },
      }),
    }),
  )
  await page.route(`${api}/api/admin/auth/me`, route =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ admin: { id: "owner", email: "admin@example.com", role: "owner" } }),
    }),
  )
  await page.route(`${api}/api/admin/stats`, route =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        total: 1,
        total_active: 1,
        new_today: 1,
        pro_team: 1,
        revoked: 0,
        week_delta: 1,
        today_delta: 1,
      }),
    }),
  )
  await page.route(`${api}/api/admin/licenses`, route =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify([license]) }),
  )
  await page.route(`${api}/api/admin/contacts`, route =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          email: "alpha@example.com",
          name: "Alpha Buyer",
          company: "Acme",
          source: "Direct",
          follow_up_date: "2026-07-28",
          stage: "trial",
          notes: "follow up",
          latest_activity: "2026-07-21T10:00:00",
          keys: [license],
        },
      ]),
    }),
  )
  await page.route(`${api}/api/admin/audit`, route =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          ts: "2026-07-21T10:00:00",
          action: "issue_license",
          target: license.key,
          details: { tier: "pro", email: "alpha@example.com" },
          actor_id: "owner",
          actor_email: "admin@example.com",
          actor_role: "owner",
          request_id: "e2e-request",
          ip: "127.0.0.1",
        },
      ]),
    }),
  )
  await page.route(`${api}/api/admin/settings`, route =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        smtp: { host: "", port: 587, user: "", password: "not set", from: "", configured: false },
        app_url: "http://localhost:3000",
        admin_auth: "cookie_session",
        data_dir: "/tmp/pushkey",
        license_count: 1,
        event_count: 1,
        version: "0.1.0",
      }),
    }),
  )
  await page.route(`${api}/api/admin/tickets`, route =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "ticket-1",
          email: "alpha@example.com",
          subject: "Activation help",
          message: "User needs setup help",
          priority: "medium",
          status: "open",
          created_at: "2026-07-21T10:00:00",
          updated_at: "2026-07-21T10:00:00",
          replies: [],
        },
      ]),
    }),
  )
})

test("admin console covers license, contact, audit, settings, and support journeys", async ({ page }) => {
  await page.goto("/admin/login")
  await expect(page.getByLabel("Admin email")).toBeVisible()
  await expect(page.getByLabel("Admin password")).toBeVisible()
  await expect(page.getByLabel("MFA code")).toBeVisible()
  await page.getByLabel("Admin email").fill("admin@example.com")
  await page.getByLabel("Admin password").fill("admin-pass-123")
  await page.getByRole("button", { name: "Sign In" }).click()

  await expect(page).toHaveURL(/\/admin\/licenses/)
  await expect(page.getByRole("link", { name: /Licenses/ })).toHaveAttribute("aria-current", "page")
  await expect(page.getByText("License Activations")).toBeVisible()
  await expect(page.getByText("Alpha Buyer")).toBeVisible()

  await page.getByRole("link", { name: /Contacts/ }).click()
  await expect(page.getByText("Contacts")).toBeVisible()
  await expect(page.getByText("Alpha Buyer")).toBeVisible()

  await page.getByRole("link", { name: /Audit Log/ }).click()
  await expect(page.getByText("Audit Log")).toBeVisible()
  await expect(page.getByRole("table").getByText("Issued")).toBeVisible()
  await expect(page.getByText("admin@example.com")).not.toBeVisible()

  await page.getByRole("link", { name: /Settings/ }).click()
  await expect(page.getByText("Settings")).toBeVisible()
  await expect(page.getByText("Admin Authentication")).toBeVisible()
  await expect(page.getByText("No admin secret in localStorage")).toBeVisible()

  await page.getByRole("link", { name: /Support/ }).click()
  await expect(page.getByText("Support")).toBeVisible()
  await expect(page.getByText("Activation help")).toBeVisible()
})
