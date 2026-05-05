"use client";

import { getToken } from "./auth";

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
    const detail = (json as { detail?: string })?.detail ?? text ?? res.statusText;
    throw new ApiError(res.status, String(detail));
  }
  return json as T;
}

// ── typed wrappers ────────────────────────────────────────────────────

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

export const api = {
  status:    () => request<StatusResp>("/api/status"),
  unlock:    (body: { password?: string; recovery_code?: string }) =>
              request<{ locked: boolean; key_count: number; can_write: boolean; auth_method: string }>("/api/unlock", { body }),
  lock:      () => request<{ locked: true }>("/api/lock", { method: "POST" }),
  listKeys:  () => request<{ keys: KeySummary[]; count: number }>("/api/keys"),
  revealKey: (name: string) => request<KeyDetail>(`/api/keys/${encodeURIComponent(name)}`),
};
