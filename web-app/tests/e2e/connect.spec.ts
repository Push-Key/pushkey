import { expect, test, type Page } from "@playwright/test";
import {
  KEY,
  PROJECT_ADMIN,
  PROJECT_OLD,
  SUGGEST,
  THREE_CONNECTIONS,
  connection,
  installRoutes,
  writtenResult,
  type MockOptions,
  type RecordedRequest,
} from "./support/mock-local-api";

const TRACKED = "this file is committed to git; Pushkey will not write secrets into it";

function writes(requests: RecordedRequest[], method: string, path: string) {
  return requests.filter((r) => r.method === method && r.path === path);
}

async function openVault(page: Page, options: MockOptions) {
  await installRoutes(page, false, options);
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Vault" }).click();
  await expect(page.getByLabel("Search keys or providers")).toBeVisible();
}

async function fillAddForm(page: Page) {
  await page.getByRole("button", { name: "Add key" }).click();
  await page.locator("#add-name").fill("OPENAI_API_KEY");
  await page.locator("#add-value").fill("sk-test-value-123");
}

const ADD_OPTIONS: MockOptions = {
  projects: [PROJECT_ADMIN],
  suggest: SUGGEST,
};

test("add and connect sends the chosen project, file and variable", async ({ page }) => {
  const requests: RecordedRequest[] = [];
  await openVault(page, {
    ...ADD_OPTIONS,
    requests,
    keyPostReplies: [
      { status: 201, body: { name: "OPENAI_API_KEY", provider: "openai", env: "dev", connection: writtenResult() } },
    ],
  });
  await fillAddForm(page);

  await expect(page.getByLabel("Connect to a project")).toBeChecked();
  await expect(
    page.getByText("Save to admin-portal -> dev -> .env.local as NEXT_PUBLIC_OPENAI_API_KEY"),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /NEXT_PUBLIC_OPENAI_API_KEY/ })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: "Save & connect" }).click();

  await expect(page.getByText("Connected: admin-portal -> .env.local as NEXT_PUBLIC_OPENAI_API_KEY")).toBeVisible();
  await expect(page.getByRole("button", { name: "See where it is used" })).toBeVisible();

  const posts = writes(requests, "POST", "/api/keys");
  expect(posts).toHaveLength(1);
  const body = posts[0].body as { name: string; connect: Record<string, unknown> };
  expect(body.name).toBe("OPENAI_API_KEY");
  expect(body.connect).toEqual({
    project: "/work/admin-portal",
    file: ".env.local",
    var: "NEXT_PUBLIC_OPENAI_API_KEY",
  });
});

test("unchecking connect saves in the vault only and sends no connect block", async ({ page }) => {
  const requests: RecordedRequest[] = [];
  await openVault(page, { ...ADD_OPTIONS, requests });
  await fillAddForm(page);

  await expect(page.getByLabel("Connect to a project")).toBeChecked();
  await page.getByLabel("Connect to a project").uncheck();
  await expect(page.getByText("Saved in the vault only. Nothing is written to a project.")).toBeVisible();
  await page.getByRole("button", { name: "Save", exact: true }).click();

  await expect.poll(() => writes(requests, "POST", "/api/keys").length).toBe(1);
  const body = writes(requests, "POST", "/api/keys")[0].body as Record<string, unknown>;
  expect(body.connect).toBeUndefined();
});

test("a preview that needs confirmation shows the panel before anything is saved", async ({ page }) => {
  const requests: RecordedRequest[] = [];
  await openVault(page, {
    ...ADD_OPTIONS,
    requests,
    previewOverride: { needs_confirm: ["env_mismatch"] },
    keyPostReplies: [
      { status: 201, body: { name: "OPENAI_API_KEY", provider: "openai", env: "dev", connection: writtenResult() } },
    ],
  });
  await fillAddForm(page);
  await expect(page.getByText("Save to admin-portal", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Save & connect" }).click();

  await expect(page.getByText("This key is for another environment. Continue?")).toBeVisible();
  expect(writes(requests, "POST", "/api/keys")).toHaveLength(0);

  // "Go back" posts nothing.
  await page.getByRole("button", { name: "Go back" }).click();
  await expect(page.getByText("This key is for another environment. Continue?")).toHaveCount(0);
  expect(writes(requests, "POST", "/api/keys")).toHaveLength(0);

  await page.getByRole("button", { name: "Save & connect" }).click();
  await page.getByRole("button", { name: "Confirm and save" }).click();
  await expect(page.getByText("Connected: admin-portal", { exact: false })).toBeVisible();

  const posts = writes(requests, "POST", "/api/keys");
  expect(posts).toHaveLength(1);
  const body = posts[0].body as { connect: { confirmed?: string[] } };
  expect(body.connect.confirmed).toEqual(["env_mismatch"]);
});

test("a 409 confirmation_required answer opens the same panel", async ({ page }) => {
  const requests: RecordedRequest[] = [];
  await openVault(page, {
    ...ADD_OPTIONS,
    requests,
    keyPostReplies: [
      { status: 409, body: { detail: "confirmation_required", needs: ["public_prefix"] } },
      { status: 201, body: { name: "OPENAI_API_KEY", provider: "openai", env: "dev", connection: writtenResult() } },
    ],
  });
  await fillAddForm(page);
  await expect(page.getByText("Save to admin-portal", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Save & connect" }).click();
  await expect(page.getByText("This name is bundled into browser code. Continue?")).toBeVisible();
  expect(writes(requests, "POST", "/api/keys")).toHaveLength(1);

  await page.getByRole("button", { name: "Confirm and save" }).click();
  await expect(page.getByText("Connected: admin-portal", { exact: false })).toBeVisible();

  const posts = writes(requests, "POST", "/api/keys");
  expect(posts).toHaveLength(2);
  const second = posts[1].body as { connect: { confirmed?: string[] } };
  expect(second.connect.confirmed).toEqual(["public_prefix"]);
});

test("a git-tracked target is refused in the preview and Save stays disabled", async ({ page }) => {
  await openVault(page, {
    ...ADD_OPTIONS,
    previewError: { status: 400, body: { detail: "file_tracked_by_git" } },
  });
  await fillAddForm(page);

  await expect(page.getByRole("alert").filter({ hasText: TRACKED })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save & connect" })).toBeDisabled();
});

test("an add that could not write the file is not shown as a plain success", async ({ page }) => {
  await openVault(page, {
    ...ADD_OPTIONS,
    keyPostReplies: [
      {
        status: 201,
        body: {
          name: "OPENAI_API_KEY",
          provider: "openai",
          env: "dev",
          connection: writtenResult({ written: false, reason: "write_failed", change: "none" }),
        },
      },
    ],
  });
  await fillAddForm(page);
  await expect(page.getByText("Save to admin-portal", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Save & connect" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "Not written" })).toBeVisible();
  await expect(page.getByText(/^Written:/)).toHaveCount(0);
});

test("Update now reports a file that could not be written as an alert", async ({ page }) => {
  const requests: RecordedRequest[] = [];
  await openVault(page, {
    keys: [KEY],
    connections: THREE_CONNECTIONS,
    requests,
    syncReply: {
      status: 200,
      body: {
        synced: [
          writtenResult({
            project: "/work/admin-portal",
            file: ".env",
            var: "OPENAI_API_KEY",
            written: false,
            reason: "file_tracked_by_git",
            change: "none",
          }),
        ],
      },
    },
  });

  await page.getByRole("button", { name: "Used in OPENAI_API_KEY" }).click();
  await page.getByRole("button", { name: "Update OPENAI_API_KEY in admin-portal" }).click();

  await expect(page.getByRole("alert").filter({ hasText: TRACKED })).toBeVisible();
  const syncs = writes(requests, "POST", "/api/connections/sync");
  expect(syncs).toHaveLength(1);
  expect(syncs[0].body).toEqual({ key: "OPENAI_API_KEY", project: "/work/admin-portal" });
});

test("Disconnect sends the exact connection and keeps the line in the file", async ({ page }) => {
  const requests: RecordedRequest[] = [];
  await openVault(page, { keys: [KEY], connections: THREE_CONNECTIONS, requests });
  page.once("dialog", (dialog) => {
    expect(dialog.message()).toContain("The line stays in .env");
    void dialog.accept();
  });

  await page.getByRole("button", { name: "Used in OPENAI_API_KEY" }).click();
  await page.getByRole("button", { name: "Disconnect OPENAI_API_KEY from admin-portal .env" }).click();

  await expect.poll(() => writes(requests, "DELETE", "/api/connections").length).toBe(1);
  expect(writes(requests, "DELETE", "/api/connections")[0].body).toEqual({
    key: "OPENAI_API_KEY",
    project: "/work/admin-portal",
    file: ".env",
    var: "OPENAI_API_KEY",
  });
});

test("rotate shows what happened to every connected file", async ({ page }) => {
  await openVault(page, {
    keys: [KEY],
    rotateReply: {
      status: 200,
      body: {
        name: "OPENAI_API_KEY",
        rotated: "2026-11-22T09:00:00",
        synced: [
          writtenResult({ project: "/work/acme-web", file: ".env.local" }),
          writtenResult({ project: "/work/billing-worker", file: ".env.production.local", written: false, reason: "folder_missing", change: "none" }),
        ],
      },
    },
  });

  await page.getByRole("button", { name: "Rotate OPENAI_API_KEY" }).click();
  await page.getByLabel("New value for OPENAI_API_KEY").fill("sk-new-value-456");
  await page.getByRole("button", { name: "Rotate", exact: true }).click();

  await expect(page.getByText("Skipped: folder not on this computer")).toBeVisible();
  await expect(page.getByText("acme-web .env.local: Updated")).toBeVisible();
});

test("the notice stays on Later and goes only on an explicit Hide this notice", async ({ page }) => {
  const requests: RecordedRequest[] = [];
  const notice = { every_key_projects: ["/work/old-site"], env_skipped: [], unusable: [], unregistered: [] };
  await installRoutes(page, false, { notice, projects: [PROJECT_OLD], requests });
  await page.goto("/#t=launch-token", { waitUntil: "commit" });

  const banner = page.getByRole("region", { name: "1 project used to get every key" });
  await expect(banner).toBeVisible();
  await expect(banner.getByText("old-site")).toBeVisible();

  await banner.getByRole("button", { name: "Later" }).click();
  await expect(banner).toHaveCount(0);
  expect(writes(requests, "DELETE", "/api/connect/notice")).toHaveLength(0);

  // Later is for this page load only: the notice is still there next time.
  await page.reload({ waitUntil: "commit" });
  await expect(banner).toBeVisible();

  await banner.getByRole("button", { name: "Hide this notice" }).click();
  await expect(banner).toHaveCount(0);
  expect(writes(requests, "DELETE", "/api/connect/notice")).toHaveLength(1);
});

test("a failed Hide this notice keeps the banner and says so", async ({ page }) => {
  const notice = { every_key_projects: ["/work/old-site"] };
  await installRoutes(page, false, { notice, projects: [PROJECT_OLD], noticeDeleteStatus: 500 });
  await page.goto("/#t=launch-token", { waitUntil: "commit" });

  const banner = page.getByRole("region", { name: "1 project used to get every key" });
  await banner.getByRole("button", { name: "Hide this notice" }).click();
  await expect(banner).toBeVisible();
  await expect(banner.getByRole("alert")).toBeVisible();
});

test("Pick keys opens that project on the Projects tab", async ({ page }) => {
  const notice = { every_key_projects: ["/work/old-site"] };
  await installRoutes(page, false, { notice, projects: [PROJECT_OLD] });
  await page.goto("/#t=launch-token", { waitUntil: "commit" });

  await page.getByRole("button", { name: "Pick keys for old-site" }).click();
  await expect(page.getByRole("button", { name: /^old-site/ })).toHaveAttribute("aria-expanded", "true");
});

test("Pick keys opens the project also when the Projects tab is already showing", async ({ page }) => {
  const notice = { every_key_projects: ["/work/old-site"] };
  await installRoutes(page, false, { notice, projects: [PROJECT_ADMIN, PROJECT_OLD] });
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Projects" }).click();
  const card = page.getByRole("button", { name: /^old-site/ });
  await expect(card).toHaveAttribute("aria-expanded", "false");

  await page.getByRole("button", { name: "Pick keys for old-site" }).click();
  await expect(card).toHaveAttribute("aria-expanded", "true");
});

async function addProjectExpecting(page: Page, reply: { status: number; body: unknown }, text: string) {
  await installRoutes(page, false, { projectPostReply: reply });
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Projects" }).click();
  await page.getByLabel("Path").fill("/work/another");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: text })).toBeVisible();
}

test("a project limit error reads as a sentence", async ({ page }) => {
  await addProjectExpecting(page, { status: 402, body: { detail: "project_limit" } }, "project limit");
});

test("a busy settings file asks the user to try again", async ({ page }) => {
  await addProjectExpecting(page, { status: 503, body: { detail: "config_busy" } }, "Try again in a moment");
});

test("Update all on a project reports every connection", async ({ page }) => {
  const requests: RecordedRequest[] = [];
  await installRoutes(page, false, {
    projects: [PROJECT_ADMIN],
    keys: [KEY],
    connections: [connection("out_of_date"), connection("up_to_date", "admin-portal", ".env.local", "NEXT_PUBLIC_OPENAI_API_KEY")],
    requests,
    syncReply: { status: 200, body: { synced: [writtenResult({ file: ".env", var: "OPENAI_API_KEY" })] } },
  });
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Projects" }).click();
  await page.getByRole("button", { name: /admin-portal/ }).first().click();

  await expect(page.getByText("Out of date")).toBeVisible();
  await page.getByRole("button", { name: "Update all connected files for admin-portal" }).click();
  await expect(page.getByText("admin-portal .env: Updated")).toBeVisible();
  const syncs = writes(requests, "POST", "/api/connections/sync");
  expect(syncs).toHaveLength(1);
  expect(syncs[0].body).toEqual({ project: "/work/admin-portal" });
});

async function openInject(page: Page, injectReply: { status: number; body: unknown }) {
  await installRoutes(page, false, {
    projects: [PROJECT_ADMIN],
    keys: [KEY],
    connections: [connection("up_to_date")],
    injectReply,
  });
  await page.goto("/#t=launch-token", { waitUntil: "commit" });
  await page.getByRole("button", { name: "Open Projects" }).click();
  await page.getByRole("button", { name: /admin-portal/ }).first().click();
  await page.getByRole("button", { name: "Inject environment file for admin-portal" }).click();
}

test("Inject .env names a file that was not written as an alert, not as success", async ({ page }) => {
  await openInject(page, {
    status: 200,
    body: {
      injected: ["OPENAI_API_KEY"],
      skipped_existing: [],
      env_file: "/work/admin-portal/.env",
      wrote: true,
      results: [
        writtenResult({ file: ".env", var: "OPENAI_API_KEY" }),
        writtenResult({ file: ".env.local", written: false, reason: "file_tracked_by_git", change: "none" }),
      ],
    },
  });

  const alert = page.getByRole("alert").filter({ hasText: ".env.local" });
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(TRACKED);
  await expect(page.getByText("Wrote:")).toHaveCount(0);
  await expect(page.getByText(".env injected")).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: ".env.local" })).toHaveCount(0);
  await expect(page.getByText("Some files were not written")).toBeVisible();
});

test("Inject .env with every file written keeps the green result and the success toast", async ({ page }) => {
  await openInject(page, {
    status: 200,
    body: {
      injected: ["OPENAI_API_KEY"],
      skipped_existing: [],
      env_file: "/work/admin-portal/.env",
      wrote: true,
      results: [writtenResult({ file: ".env", var: "OPENAI_API_KEY" })],
    },
  });

  await expect(page.getByText("Wrote: /work/admin-portal/.env")).toBeVisible();
  await expect(page.getByText(".env injected")).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Not written" })).toHaveCount(0);
});
