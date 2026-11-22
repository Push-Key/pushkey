"use client";

import { clearToken, getToken } from "./auth";

const BASE = (typeof window !== "undefined"
  ? `${window.location.protocol}//${window.location.host}`
  : "");

export class ApiError extends Error {
  status: number;
  detail: string;
  /** Confirmations a 409 confirmation_required answer asks for (empty otherwise). */
  needs: string[];
  constructor(status: number, detail: string, needs: string[] = []) {
    super(`${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
    this.needs = needs;
  }
}

function needsFrom(json: unknown): string[] {
  const needs = (json as { needs?: unknown } | undefined)?.needs;
  return Array.isArray(needs) ? needs.filter((n): n is string => typeof n === "string") : [];
}

function cleanQuery(q: Record<string, string | undefined>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(q)) if (v) out[k] = v;
  return out;
}

async function request<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Record<string, string | number | boolean> } = {}
): Promise<T> {
  const tok = getToken();
  if (!tok) throw new ApiError(401, "no launch token in session");
  let url = `${BASE}${path}`;
  if (opts.query) {
    const usp = new URLSearchParams();
    Object.entries(opts.query).forEach(([k, v]) => usp.set(k, String(v)));
    url += `?${usp.toString()}`;
  }
  const res = await fetch(url, {
    method: opts.method || (opts.body !== undefined ? "POST" : "GET"),
    headers: {
      Authorization: `Bearer ${tok}`,
      ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let json: unknown = undefined;
  try { json = text ? JSON.parse(text) : undefined; } catch { /* not json */ }
  if (!res.ok) {
    if (res.status === 401) clearToken();
    const detail = (json as { detail?: string })?.detail ?? text ?? res.statusText;
    throw new ApiError(res.status, String(detail), needsFrom(json));
  }
  return json as T;
}

// ── types ─────────────────────────────────────────────────────────────────────

export type StatusResp = {
  locked: boolean;
  has_vault: boolean;
  vault_schema: number;
  key_count: number;
  autolock_seconds: number;
  idle_seconds: number;
  auth_method: string;
  can_write: boolean;
};

export type KeySummary = {
  name: string;
  env: string;
  /** How many project files this key is connected to. */
  connections: number;
  rotated: string | null;
  added: string | null;
  provider: string | null;
  dual_rotation: boolean;
  has_backup: boolean;
  history_count: number;
  team_role: string | null;
  masked: string;
};

export type KeyDetail = KeySummary & {
  value: string;
  next_value: string | null;
  next_added: string | null;
  history: { value: string; retired: string }[];
  projects: string[];
  notes: string;
};

export type Project = {
  path: string;
  name: string;
  keys: string[];
  created: string | null;
  connections: number;
};

export type HealthEntry = {
  name: string;
  provider: string;
  env: string;
  age_days: number;
  status: "healthy" | "warning" | "critical";
};

export type HealthResp = {
  total: number;
  healthy: HealthEntry[];
  stale: HealthEntry[];
  unknown_provider: string[];
  backup_missing: string[];
  score: number;
  threshold_days: number;
};

export type ForecastItem = {
  name: string;
  provider: string;
  env: string;
  due_date: string;
  days_left: number;
  overdue: boolean;
  has_backup: boolean;
};

export type LifecycleResp = {
  name: string;
  provider: string;
  env: string;
  created: string | null;
  rotated: string | null;
  age_days: number | null;
  rotation_interval_days: number;
  next_due_date: string | null;
  status: string;
  dual_rotation: boolean;
  next_value_present: boolean;
  next_added: string | null;
  history: { value: string; retired: string }[];
  projects: string[];
};

export type AuditEvent = {
  timestamp?: string;
  message?: string;
  raw?: string;
};

export type AgentToken = {
  id: string;
  name: string;
  scopes: string[];
  created?: string;
};

export type Confirmation = "env_mismatch" | "public_prefix";

export type ConnectRef = {
  project: string;
  file?: string;
  var?: string;
  confirmed?: string[];
};

/** What saving would do (POST /api/connections/preview). Names only, never a value. */
export type Preview = {
  key: string;
  project: string;
  project_name: string;
  file: string;
  var: string;
  environment: string;
  line: string;
  change: "add" | "replace" | "none";
  gitignore_change: boolean;
  needs_confirm: string[];
  conflict_key: string | null;
};

/** What a connect, sync or inject did for one file. `written: false` is never a quiet success. */
export type ConnectResult = {
  key: string;
  project: string;
  file: string;
  var: string;
  written: boolean;
  reason: string | null;
  change: string;
  gitignore_changed: boolean;
  health_warning: string | null;
  warning: string | null;
};

export type ConnectionState =
  | "up_to_date"
  | "out_of_date"
  | "not_in_file"
  | "file_missing"
  | "folder_missing"
  | "not_ignored"
  | "not_written";

export type ConnectionStatus = {
  key: string;
  project: string;
  project_name: string;
  file: string;
  var: string;
  state: ConnectionState;
  /** A code (see describeReason) or, for old errors, free text. Never trust it to be a code. */
  reason: string | null;
};

/** Each pair is [value, reason it was suggested]. */
export type Suggestion = {
  projects: [string, string][];
  files: [string, string][];
  vars: [string, string][];
};

export type ConnectNotice = {
  every_key_projects?: string[];
  env_skipped?: [string, string][];
  unusable?: string[];
  unregistered?: [string, string][];
};

export type RotateResp = {
  name: string;
  rotated: string;
  history_count?: number;
  synced?: ConnectResult[];
  not_synced?: { project: string; file: string; var: string }[];
  sync_error?: string;
};

export type AddKeyResp = {
  name: string;
  provider: string | null;
  env: string;
  connection?: ConnectResult;
  synced?: ConnectResult[];
  not_synced?: { project: string; file: string; var: string }[];
  sync_error?: string;
};

export type InjectResp = {
  injected: string[];
  skipped_existing: string[];
  env_file: string;
  wrote: boolean;
  results?: ConnectResult[];
};

// ── error and reason text ─────────────────────────────────────────────────────
// One table for every screen. None of these texts can hold a secret value: the
// local API sends codes, names and paths only.

export const FILE_TRACKED_TEXT = "this file is committed to git; Pushkey will not write secrets into it";

const REASON_TEXT: Record<string, string> = {
  file_tracked_by_git: FILE_TRACKED_TEXT,
  project_limit: "Your plan's project limit is reached. Remove a project or upgrade to add another.",
  project_exists: "That folder is already a project.",
  migration_pending:
    "Project setup is not finished. Lock the vault and unlock it with your master password to finish it.",
  config_unreadable: "The project settings file could not be read. Nothing was changed.",
  config_busy: "Another Pushkey process is using the project settings. Try again in a moment.",
  var_taken:
    "Conflict: another key already writes to that variable in that file. Pick a different variable or file.",
  project_not_registered: "That folder is not a registered project. Add it in the Projects tab first.",
  invalid_var: "That variable name is not valid. Use letters, digits and underscores, and do not start with a digit.",
  invalid_env_file: "That env file is not valid UTF-8 text or has an unclosed quote.",
  key_exists: "A key with that name already exists.",
  key_not_found: "That key is no longer in the vault.",
  connection_not_found: "That connection no longer exists.",
  vault_changed: "The vault changed on disk. Lock and unlock, then retry.",
  vault_unavailable: "The vault changed on disk. Lock and unlock, then retry.",
  read_failed: "The env file could not be read. Nothing was changed.",
  backup_failed: "A backup of the env file could not be made, so it was not changed.",
  write_failed: "The env file could not be written.",
  folder_missing: "The folder is not on this computer.",
  confirmation_required: "This needs your confirmation.",
};

/** Text for a ConnectResult.reason or ConnectionStatus.reason: a known code, else the text as sent. */
export function reasonText(reason: string | null | undefined): string {
  if (!reason) return "the file could not be updated";
  return REASON_TEXT[reason] ?? reason;
}

/** Text for any failed call. Known codes become sentences; anything else is shown as sent. */
export function describeApiError(e: unknown, fallback = "request failed"): string {
  if (e instanceof ApiError) {
    if (e.status === 403 && (
      e.detail.startsWith("agent token missing required scope") ||
      e.detail.startsWith("write requires master-password unlock")
    )) {
      return "This session cannot do that. Unlock with your master password.";
    }
    if (e.detail === "file_tracked_by_git") return `Not written: ${FILE_TRACKED_TEXT}`;
    const known = REASON_TEXT[e.detail];
    if (known) return known;
    return e.detail || fallback;
  }
  return e instanceof Error ? e.message : fallback;
}

// ── api client ────────────────────────────────────────────────────────────────

export const api = {
  // auth
  status:    () => request<StatusResp>("/api/status"),
  unlock:    (body: { password?: string; recovery_code?: string }) =>
              request<{ locked: boolean; key_count: number; can_write: boolean; auth_method: string }>("/api/unlock", { body }),
  lock:      () => request<{ locked: true }>("/api/lock", { method: "POST" }),

  // keys
  listKeys:  () => request<{ keys: KeySummary[]; count: number }>("/api/keys"),
  revealKey: (name: string) => request<KeyDetail>(`/api/keys/${encodeURIComponent(name)}`),
  addKey:    (body: {
                name: string; value: string; provider?: string; env?: string; notes?: string;
                overwrite?: boolean; connect?: ConnectRef;
              }) => request<AddKeyResp>("/api/keys", { body }),
  updateKey: (name: string, body: { provider?: string; env?: string; notes?: string }) =>
              request<KeySummary>(`/api/keys/${encodeURIComponent(name)}`, { method: "PATCH", body }),
  deleteKey: (name: string) =>
              request<void>(`/api/keys/${encodeURIComponent(name)}`, { method: "DELETE" }),
  rotateKey: (name: string, new_value: string) =>
              request<RotateResp>(`/api/keys/${encodeURIComponent(name)}/rotate`, { body: { new_value } }),
  setBackup: (name: string, backup_value: string) =>
              request<unknown>(`/api/keys/${encodeURIComponent(name)}/backup`, { body: { backup_value } }),
  promote:   (name: string) =>
              request<RotateResp>(`/api/keys/${encodeURIComponent(name)}/promote`, { body: {} }),

  // projects
  listProjects:   () => request<{ projects: Project[]; count: number }>("/api/projects"),
  createProject:  (path: string, name?: string) =>
                   request<{ path: string; name: string }>("/api/projects", { body: { path, name } }),
  deleteProject:  (path: string) =>
                   request<void>(`/api/projects?path=${encodeURIComponent(path)}`, { method: "DELETE" }),
  assignKeys:     (path: string, keys: string[], confirmed?: string[]) =>
                   request<{ path: string; assigned: string[] }>(`/api/projects/assign?path=${encodeURIComponent(path)}`, { body: { keys, confirmed } }),
  unassignKeys:   (path: string, keys: string[]) =>
                   request<{ path: string; unassigned: string[] }>(`/api/projects/unassign?path=${encodeURIComponent(path)}`, { body: { keys } }),
  injectProject:  (path: string, preview?: boolean) =>
                   request<InjectResp>(
                     `/api/projects/inject?path=${encodeURIComponent(path)}&write=${!preview}`, { body: {} }),

  // connections: which project file a key is written to
  previewConnection: (body: { key: string; project: string; file?: string; var?: string; value?: string; env?: string }) =>
                   request<Preview>("/api/connections/preview", { body }),
  connect:        (body: { key: string } & ConnectRef) =>
                   request<ConnectResult>("/api/connections", { body }),
  disconnect:     (body: { key: string; project: string; file: string; var: string }) =>
                   request<{ key: string; project: string; file: string; var: string; disconnected: boolean }>("/api/connections", { method: "DELETE", body }),
  listConnections: (q: { key?: string; project?: string } = {}) =>
                   request<{ connections: ConnectionStatus[] }>("/api/connections", { query: cleanQuery(q) }),
  syncConnections: (body: { key?: string; project?: string } = {}) =>
                   request<{ synced: ConnectResult[] }>("/api/connections/sync", { body }),
  suggestConnection: (key: string, project?: string) =>
                   request<Suggestion>("/api/connections/suggest", { query: cleanQuery({ key, project }) }),
  getNotice:      () => request<{ notice: ConnectNotice | null }>("/api/connect/notice"),
  dismissNotice:  () => request<void>("/api/connect/notice", { method: "DELETE" }),

  // health
  getHealth:   (threshold_days?: number) =>
                request<HealthResp>("/api/health", { query: threshold_days ? { threshold_days } : {} }),

  // forecast
  getForecast: (window_days?: number) =>
                request<{ upcoming: ForecastItem[]; count: number; window_days: number }>(
                  "/api/forecast", { query: window_days ? { window_days } : {} }),

  // lifecycle
  getLifecycle: (name: string) =>
                 request<LifecycleResp>(`/api/lifecycle/${encodeURIComponent(name)}`),

  // audit
  getAudit: (limit?: number) =>
             request<{ events: AuditEvent[]; count: number }>("/api/audit", { query: limit ? { limit } : {} }),

  // agents
  listAgents:   () => request<{ tokens: AgentToken[] }>("/api/agents"),
  createAgent:  (name: string, scopes: string[]) =>
                 request<{ id: string; token: string; name: string; scopes: string[] }>("/api/agents", { body: { name, scopes } }),
  revokeAgent:  (token_id: string) =>
                 request<void>(`/api/agents/${encodeURIComponent(token_id)}`, { method: "DELETE" }),

  // settings / vault ops
  exportBackup: () => request<{ blob_b64: string }>("/api/backup/export", { body: {} }),
  importBackup: (blob_b64: string) => request<{ imported: boolean; bytes: number }>("/api/backup/import", { body: { blob_b64 } }),

  // recovery / rekey
  addRecovery: (password: string) =>
                request<{ recovery_code: string }>("/api/recovery/add", { body: { password } }),
  rekey:       (recovery_code: string, new_password: string) =>
                request<{ ok: boolean }>("/api/vault/rekey", { body: { recovery_code, new_password } }),
};
