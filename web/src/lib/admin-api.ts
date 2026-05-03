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
}

export interface AdminStats {
  total: number
  total_active: number
  new_today: number
  pro_team: number
  revoked: number
  week_delta: number
  today_delta: number
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

  async exportCsv(s: string): Promise<void> {
    const r = await fetch(`${API}/api/admin/export`, { headers: h(s) })
    if (!r.ok) throw new Error("Export failed")
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = "licenses.csv"
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
