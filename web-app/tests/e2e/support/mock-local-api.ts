import type { Page, Route } from "@playwright/test";

export type RecordedRequest = { method: string; path: string; query: string; body: unknown };
export type MockReply = { status: number; body?: unknown };

export type MockKey = {
  name: string;
  env: string;
  rotated: string | null;
  added: string | null;
  provider: string | null;
  dual_rotation: boolean;
  has_backup: boolean;
  history_count: number;
  team_role: string | null;
  masked: string;
  connections: number;
};

export type MockProject = {
  path: string;
  name: string;
  keys: string[];
  created: string | null;
  connections: number;
};

export type MockConnection = {
  key: string;
  project: string;
  project_name: string;
  file: string;
  var: string;
  state: string;
  reason: string | null;
};

export type MockOptions = {
  /** Number of stale keys, which renders the sidebar health count badge. */
  stale?: number;
  /** Number of overdue rotations, which renders the forecast count badge. */
  overdue?: number;
  keys?: MockKey[];
  projects?: MockProject[];
  /** What GET /api/connections answers (filtered by the key and project query). */
  connections?: MockConnection[];
  /** What GET /api/connect/notice answers; null (default) means no notice. */
  notice?: unknown;
  /** Status of DELETE /api/connect/notice (default 204). */
  noticeDeleteStatus?: number;
  /** What GET /api/connections/suggest answers. */
  suggest?: { projects: [string, string][]; files: [string, string][]; vars: [string, string][] };
  /** Fields merged over the generated preview. */
  previewOverride?: Record<string, unknown>;
  /** When set, POST /api/connections/preview answers this instead of a preview. */
  previewError?: MockReply;
  /** Answers to POST /api/keys in order; the last one repeats. */
  keyPostReplies?: MockReply[];
  /** Answer to POST /api/connections/sync. */
  syncReply?: MockReply;
  /** Answer to POST /api/keys/{name}/rotate. */
  rotateReply?: MockReply;
  /** Answer to POST /api/projects. */
  projectPostReply?: MockReply;
  /** Answer to POST /api/projects/assign. */
  assignReplies?: MockReply[];
  /** Every write the app sends (method, path, query, JSON body) is pushed here. */
  requests?: RecordedRequest[];
};

export const KEY: MockKey = {
  name: "OPENAI_API_KEY",
  env: "dev",
  rotated: "2026-11-01T10:30:00",
  added: "2026-10-01",
  provider: "openai",
  dual_rotation: false,
  has_backup: false,
  history_count: 0,
  team_role: null,
  masked: "sk-…abcd",
  connections: 3,
};

export const PROJECT_ADMIN: MockProject = {
  path: "/work/admin-portal",
  name: "admin-portal",
  keys: ["OPENAI_API_KEY"],
  created: "2026-10-01",
  connections: 1,
};

export const PROJECT_OLD: MockProject = {
  path: "/work/old-site",
  name: "old-site",
  keys: [],
  created: "2026-09-01",
  connections: 0,
};

export function connection(
  state: string,
  project = "admin-portal",
  file = ".env",
  variable = "OPENAI_API_KEY",
  reason: string | null = null,
): MockConnection {
  return {
    key: "OPENAI_API_KEY",
    project: `/work/${project}`,
    project_name: project,
    file,
    var: variable,
    state,
    reason,
  };
}

export const THREE_CONNECTIONS: MockConnection[] = [
  connection("up_to_date", "acme-web", ".env.local", "NEXT_PUBLIC_OPENAI_API_KEY"),
  connection("out_of_date", "admin-portal", ".env", "OPENAI_API_KEY"),
  connection("folder_missing", "billing-worker", ".env.production.local", "OPENAI_KEY"),
];

export const SUGGEST: NonNullable<MockOptions["suggest"]> = {
  projects: [["/work/admin-portal", "last used"]],
  files: [
    [".env.local", "Next.js or Vite project"],
    [".env", "default env file"],
  ],
  vars: [
    ["NEXT_PUBLIC_OPENAI_API_KEY", "found in .env.example"],
    ["OPENAI_API_KEY", "same as the key name"],
  ],
};

export function writtenResult(overrides: Record<string, unknown> = {}) {
  return {
    key: "OPENAI_API_KEY",
    project: "/work/admin-portal",
    file: ".env.local",
    var: "NEXT_PUBLIC_OPENAI_API_KEY",
    written: true,
    reason: null,
    change: "add",
    gitignore_changed: false,
    health_warning: null,
    warning: null,
    ...overrides,
  };
}

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

function json(route: Route, status: number, body?: unknown) {
  if (status === 204 || body === undefined) {
    return route.fulfill({ status });
  }
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function pickReply(replies: MockReply[], index: number): MockReply {
  return replies[Math.min(index, replies.length - 1)];
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
  const keys = options.keys ?? [];
  const projects = options.projects ?? [];
  const connections = options.connections ?? [];
  const keyPostReplies = options.keyPostReplies ?? [
    { status: 201, body: { name: "OPENAI_API_KEY", provider: "openai", env: "dev" } },
  ];
  let keyPostCount = 0;
  let assignCount = 0;

  const record = (route: Route) => {
    const request = route.request();
    if (!options.requests) return;
    const url = new URL(request.url());
    let body: unknown = null;
    try {
      body = request.postDataJSON();
    } catch {
      body = null;
    }
    options.requests.push({
      method: request.method(),
      path: url.pathname,
      query: url.search,
      body,
    });
  };

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
        key_count: keys.length || 2,
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

  await page.route("**/api/keys", (route) => {
    if (route.request().method() === "POST") {
      record(route);
      const reply = pickReply(keyPostReplies, keyPostCount);
      keyPostCount += 1;
      return json(route, reply.status, reply.body);
    }
    return json(route, 200, { keys, count: keys.length });
  });

  await page.route("**/api/keys/*/rotate", (route) => {
    record(route);
    const reply = options.rotateReply ?? {
      status: 200,
      body: { name: "OPENAI_API_KEY", rotated: "2026-11-22T09:00:00", synced: [] },
    };
    return json(route, reply.status, reply.body);
  });

  await page.route("**/api/projects", (route) => {
    if (route.request().method() === "POST") {
      record(route);
      const reply = options.projectPostReply ?? {
        status: 201,
        body: { path: "/work/new-project", name: "new-project" },
      };
      return json(route, reply.status, reply.body);
    }
    return json(route, 200, { projects, count: projects.length });
  });

  await page.route("**/api/projects/assign**", (route) => {
    record(route);
    const replies = options.assignReplies ?? [
      { status: 200, body: { path: "/work/admin-portal", assigned: ["OPENAI_API_KEY"] } },
    ];
    const reply = pickReply(replies, assignCount);
    assignCount += 1;
    return json(route, reply.status, reply.body);
  });

  await page.route("**/api/connections**", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    if (method !== "GET") record(route);

    if (url.pathname === "/api/connections/preview") {
      if (options.previewError) return json(route, options.previewError.status, options.previewError.body);
      const body = (request.postDataJSON() ?? {}) as Record<string, string | undefined>;
      const projectName = (body.project ?? "").split("/").pop() ?? "";
      const file = body.file ?? ".env";
      const variable = body.var ?? body.key ?? "";
      const env = body.env ?? "dev";
      return json(route, 200, {
        key: body.key,
        project: body.project,
        project_name: projectName,
        file,
        var: variable,
        environment: env,
        line: `Save to ${projectName} -> ${env} -> ${file} as ${variable}`,
        change: "add",
        gitignore_change: false,
        needs_confirm: [],
        conflict_key: null,
        ...(options.previewOverride ?? {}),
      });
    }
    if (url.pathname === "/api/connections/suggest") {
      return json(route, 200, options.suggest ?? { projects: [], files: [], vars: [] });
    }
    if (url.pathname === "/api/connections/sync") {
      const reply = options.syncReply ?? { status: 200, body: { synced: [] } };
      return json(route, reply.status, reply.body);
    }
    if (method === "DELETE") {
      const body = (request.postDataJSON() ?? {}) as Record<string, unknown>;
      return json(route, 200, { ...body, disconnected: true });
    }
    if (method === "POST") {
      return json(route, 201, writtenResult());
    }
    const key = url.searchParams.get("key");
    const project = url.searchParams.get("project");
    const rows = connections.filter(
      (c) => (key === null || c.key === key) && (project === null || c.project === project),
    );
    return json(route, 200, { connections: rows });
  });

  await page.route("**/api/connect/notice", (route) => {
    if (route.request().method() === "DELETE") {
      record(route);
      return json(route, options.noticeDeleteStatus ?? 204, options.noticeDeleteStatus && options.noticeDeleteStatus >= 400 ? { detail: "write_failed" } : undefined);
    }
    return json(route, 200, { notice: options.notice ?? null });
  });

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
