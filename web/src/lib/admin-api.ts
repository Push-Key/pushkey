const API = process.env.NEXT_PUBLIC_ADMIN_API_URL ?? "http://localhost:8000"

export interface License {
  key: string
  tier: "free" | "starter" | "pro" | "team" | "enterprise"
  email: string
  platform: string
  activated: string
  last_heartbeat: string | null
  status: "active" | "expired" | "revoked"
  notes: string
  // CRM fields (may be absent on older records)
  name?: string
  company?: string
  source?: string
  follow_up_date?: string
  expires_at?: string | null
  stage?: "trial" | "active" | "converted" | "churned" | "cold"
  sent_invite?: boolean
  agent_token_count?: number
}

export interface ContactKey {
  key: string
  tier: License["tier"]
  status: License["status"]
  expires_at: string | null
  activated: string
}

export interface Contact {
  email: string
  name: string
  company: string
  source: string
  follow_up_date: string
  stage: string
  notes: string
  keys: ContactKey[]
  latest_activity: string
}

export interface IssueKeyRequest {
  email: string
  tier: License["tier"]
  name?: string
  company?: string
  source?: string
  trial_days?: 7 | 14 | 30 | null
  follow_up_date?: string
  notes?: string
  send_email: boolean
}

export interface IssueKeyResponse extends License {
  email_result: { sent: boolean; reason?: string }
}

export interface AdminStats {
  total: number
  total_active: number
  new_today: number
  pro_team: number
  revoked: number
  week_delta: number
  today_delta: number
  mcp_users?: number
  total_agent_tokens?: number
}

export interface SupportTicket {
  id: string
  email: string
  subject: string
  message: string
  priority: "low" | "medium" | "high"
  status: "open" | "pending" | "resolved"
  created_at: string
  updated_at: string
  replies: { ts: string; body: string }[]
}

export interface AuditEntry {
  ts: string
  action: string
  target: string
  details: Record<string, unknown>
}

export interface AdminSettings {
  smtp: {
    host: string
    port: number
    user: string
    password: string
    from: string
    configured: boolean
  }
  app_url: string
  admin_secret_set: boolean
  data_dir: string
  license_count: number
  event_count: number
  version: string
}

function h(secret: string): HeadersInit {
  return { "Content-Type": "application/json", "X-Admin-Secret": secret }
}

async function call<T>(secret: string, path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(`${API}${path}`, { ...init, headers: h(secret) })
  if (r.status === 403) throw new Error("UNAUTHORIZED")
  if (!r.ok) throw new Error(await r.text())
  const ct = r.headers.get("content-type") ?? ""
  if (!ct.includes("application/json")) return undefined as T
  return r.json()
}

export const adminApi = {
  stats: (s: string) =>
    call<AdminStats>(s, "/api/admin/stats"),

  licenses: (s: string) =>
    call<License[]>(s, "/api/admin/licenses"),

  generate: (s: string, payload: { tier: string; email: string; notes: string }) =>
    call<License>(s, "/api/admin/licenses/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  expire: (s: string, key: string) =>
    call<void>(s, `/api/admin/licenses/${encodeURIComponent(key)}/expire`, { method: "POST" }),

  revoke: (s: string, key: string) =>
    call<void>(s, `/api/admin/licenses/${encodeURIComponent(key)}/revoke`, { method: "POST" }),

  renew: (s: string, key: string) =>
    call<void>(s, `/api/admin/licenses/${encodeURIComponent(key)}/renew`, { method: "POST" }),

  analytics: (s: string) =>
    call<{
      daily_activations: { date: string; count: number }[]
      daily_heartbeats:  { date: string; count: number }[]
      event_totals: Record<string, number>
    }>(s, "/api/admin/analytics"),

  settings: (s: string) =>
    call<AdminSettings>(s, "/api/admin/settings"),

  audit: (s: string) =>
    call<AuditEntry[]>(s, "/api/admin/audit"),

  // Support tickets
  listTickets: (s: string) =>
    call<SupportTicket[]>(s, "/api/admin/tickets"),

  createTicket: (s: string, payload: { email: string; subject: string; message: string; priority: "low" | "medium" | "high" }) =>
    call<SupportTicket>(s, "/api/admin/tickets", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateTicket: (s: string, id: string, payload: { status?: SupportTicket["status"]; reply?: string }) =>
    call<SupportTicket>(s, `/api/admin/tickets/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  bulkAction: (s: string, action: "expire" | "revoke" | "renew", keys: string[]) =>
    call<{ ok: boolean; affected: number; not_found: number }>(s, "/api/admin/licenses/bulk", {
      method: "POST",
      body: JSON.stringify({ action, keys }),
    }),

  async downloadBackup(s: string): Promise<void> {
    const r = await fetch(`${API}/api/admin/backup`, { headers: h(s) })
    if (!r.ok) throw new Error("Backup failed")
    const blob = await r.blob()
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement("a")
    a.href = url
    a.download = `pushkey-backup-${new Date().toISOString().slice(0, 10)}.tar.gz`
    a.click()
    URL.revokeObjectURL(url)
  },

  testEmail: (s: string, to: string) =>
    call<{ sent: boolean; reason?: string; to?: string }>(s, "/api/admin/settings/test-email", {
      method: "POST",
      body: JSON.stringify({ to }),
    }),

  issueKey: (s: string, payload: IssueKeyRequest) =>
    call<IssueKeyResponse>(s, "/api/admin/licenses/issue", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getContacts: (s: string) =>
    call<Contact[]>(s, "/api/admin/contacts"),

  updateContact: (
    s: string,
    email: string,
    data: Partial<Pick<Contact, "name" | "company" | "follow_up_date" | "stage" | "notes" | "source">>
  ) =>
    call<{ ok: boolean; updated: number }>(
      s,
      `/api/admin/contacts/${encodeURIComponent(email)}`,
      { method: "PATCH", body: JSON.stringify(data) }
    ),

  sendInvite: (s: string, key: string) =>
    call<{ sent: boolean; reason?: string }>(
      s,
      `/api/admin/licenses/${encodeURIComponent(key)}/send-invite`,
      { method: "POST" }
    ),

  async exportCsv(s: string, filters?: { tier?: string; status?: string; search?: string }): Promise<void> {
    const params = new URLSearchParams()
    if (filters?.tier && filters.tier !== "All")     params.set("tier",   filters.tier)
    if (filters?.status && filters.status !== "All") params.set("status", filters.status)
    if (filters?.search)                              params.set("search", filters.search)
    const qs  = params.toString() ? `?${params}` : ""
    const r   = await fetch(`${API}/api/admin/export${qs}`, { headers: h(s) })
    if (!r.ok) throw new Error("Export failed")
    const blob = await r.blob()
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement("a")
    a.href = url
    a.download = qs ? "licenses-filtered.csv" : "licenses.csv"
    a.click()
    URL.revokeObjectURL(url)
  },
}

export function maskKey(key: string): string {
  const p = key.split("-")
  if (p.length < 4) return key
  return `${p[0]}-${p[1]}-•••••••••-${p[p.length - 1]}`
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "—"
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "Just now"
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} hour${hrs > 1 ? "s" : ""} ago`
  const days = Math.floor(hrs / 24)
  return `${days} day${days > 1 ? "s" : ""} ago`
}

export function fmtDate(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10)
}

export function fmtDateOrDash(iso: string | null | undefined): string {
  if (!iso) return "—"
  return new Date(iso).toISOString().slice(0, 10)
}

export function isExpiringSoon(iso: string | null | undefined): boolean {
  if (!iso) return false
  const diff = new Date(iso).getTime() - Date.now()
  return diff > 0 && diff < 7 * 24 * 60 * 60 * 1000
}

export function isOverdue(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false
  return dateStr <= new Date().toISOString().slice(0, 10)
}
