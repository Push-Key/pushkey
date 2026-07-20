"use client";

import { clearToken, getToken } from "./auth";

const BASE = (typeof window !== "undefined"
  ? `${window.location.protocol}//${window.location.host}`
  : "");

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
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
    throw new ApiError(res.status, String(detail));
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
  addKey:    (body: { name: string; value: string; provider?: string; env?: string; notes?: string }) =>
              request<KeySummary>("/api/keys", { body }),
  updateKey: (name: string, body: { provider?: string; env?: string; notes?: string }) =>
              request<KeySummary>(`/api/keys/${encodeURIComponent(name)}`, { method: "PATCH", body }),
  deleteKey: (name: string) =>
              request<void>(`/api/keys/${encodeURIComponent(name)}`, { method: "DELETE" }),
  rotateKey: (name: string, new_value: string) =>
              request<{ name: string; rotated: string }>(`/api/keys/${encodeURIComponent(name)}/rotate`, { body: { new_value } }),
  setBackup: (name: string, backup_value: string) =>
              request<unknown>(`/api/keys/${encodeURIComponent(name)}/backup`, { body: { backup_value } }),
  promote:   (name: string) =>
              request<{ name: string; rotated: string }>(`/api/keys/${encodeURIComponent(name)}/promote`, { body: {} }),

  // projects
  listProjects:   () => request<{ projects: Project[]; count: number }>("/api/projects"),
  createProject:  (path: string, name?: string) =>
                   request<{ path: string; name: string }>("/api/projects", { body: { path, name } }),
  deleteProject:  (path: string) =>
                   request<void>(`/api/projects?path=${encodeURIComponent(path)}`, { method: "DELETE" }),
  assignKeys:     (path: string, keys: string[]) =>
                   request<{ path: string; assigned: string[] }>(`/api/projects/assign?path=${encodeURIComponent(path)}`, { body: { keys } }),
  unassignKeys:   (path: string, keys: string[]) =>
                   request<{ path: string; unassigned: string[] }>(`/api/projects/unassign?path=${encodeURIComponent(path)}`, { body: { keys } }),
  injectProject:  (path: string, preview?: boolean) =>
                   request<{ injected: string[]; skipped_existing: string[]; env_file: string; wrote: boolean }>(
                     `/api/projects/inject?path=${encodeURIComponent(path)}&write=${!preview}`, { body: {} }),

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
