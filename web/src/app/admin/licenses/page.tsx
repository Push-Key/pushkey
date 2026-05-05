"use client"
import { useEffect, useState, useMemo, useCallback, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Search, Download, Plus, ChevronLeft, ChevronRight, X, Check, Copy } from "lucide-react"
import { adminApi, maskKey, timeAgo, fmtDate, fmtDateOrDash, isExpiringSoon, type License, type IssueKeyRequest, type IssueKeyResponse } from "@/lib/admin-api"
import { useAdmin } from "../_context"

// ── Tier config ──────────────────────────────────────────────────
const TIER_CFG = {
  free:       { label: "Free",       icon: "🔲", bg: "bg-sky-900/40",    text: "text-sky-300",    border: "border-sky-800/60",    maxKeys: 15,   maxProjects: 1,  maxDevices: 1,    features: [] },
  starter:    { label: "Starter",    icon: "🚀", bg: "bg-violet-900/40", text: "text-violet-300", border: "border-violet-800/60", maxKeys: 50,   maxProjects: 3,  maxDevices: 1,    features: ["Cloud sync", "Git scan"] },
  pro:        { label: "Pro",        icon: "⚡", bg: "bg-purple-900/50", text: "text-purple-200", border: "border-purple-700/60", maxKeys: null, maxProjects: null, maxDevices: 3,  features: ["Cloud sync", "CI sync", "Git scan"] },
  team:       { label: "Team",       icon: "👥", bg: "bg-teal-900/40",   text: "text-teal-300",   border: "border-teal-800/60",   maxKeys: null, maxProjects: null, maxDevices: 5,  features: ["Cloud sync", "CI sync", "Git scan", "Team RBAC"] },
  enterprise: { label: "Enterprise", icon: "🏛️", bg: "bg-amber-900/40",  text: "text-amber-300",  border: "border-amber-800/60",  maxKeys: null, maxProjects: null, maxDevices: null, features: ["Cloud sync", "CI sync", "Git scan", "Team RBAC", "Hardware MFA", "SSO", "Dynamic secrets"] },
}

function TierBadge({ tier }: { tier: License["tier"] }) {
  const c = TIER_CFG[tier] ?? TIER_CFG.free
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${c.bg} ${c.text} ${c.border}`}>
      <span>{c.icon}</span>{c.label}
    </span>
  )
}

// ── Status badge ─────────────────────────────────────────────────
const STATUS_CFG = {
  active:  { dot: "bg-emerald-400", text: "text-emerald-400", label: "Active" },
  expired: { dot: "bg-amber-400",   text: "text-amber-400",   label: "Expired" },
  revoked: { dot: "bg-red-400",     text: "text-red-400",     label: "Revoked" },
}

function StatusBadge({ status }: { status: License["status"] }) {
  const c = STATUS_CFG[status]
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${c.text}`}>
      <span className={`w-2 h-2 rounded-full ${c.dot}`} />
      {c.label}
    </span>
  )
}

function PlatformCell({ platform }: { platform: string }) {
  const p = platform.toLowerCase()
  const icon = p.includes("mac") ? "🍎" : p.includes("linux") ? "🐧" : p ? "🪟" : ""
  return (
    <span className="inline-flex items-center gap-2 text-sm text-[#94A3B8]">
      {icon} {platform || "—"}
    </span>
  )
}

function StatCard({ label, value, sub, accent }: { label: string; value: number; sub: string; accent: string }) {
  return (
    <div className="relative bg-[#0D1B2A] border border-white/8 rounded-xl p-5 overflow-hidden flex-1 min-w-0">
      <div className={`absolute left-0 top-0 bottom-0 w-1 rounded-l-xl ${accent}`} />
      <p className="text-[10px] tracking-widest uppercase text-[#94A3B8] mb-2">{label}</p>
      <p className="text-3xl font-bold text-white">{value.toLocaleString()}</p>
      <p className="text-xs text-[#94A3B8] mt-1">{sub}</p>
    </div>
  )
}

// ── View modal ───────────────────────────────────────────────────
function ViewModal({ lic, onClose }: { lic: License; onClose: () => void }) {
  const cfg = TIER_CFG[lic.tier] ?? TIER_CFG.free
  const [copied, setCopied] = useState(false)

  function copyKey() {
    navigator.clipboard.writeText(lic.key)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#0D1B2A] border border-white/10 rounded-2xl p-6 w-full max-w-lg shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <TierBadge tier={lic.tier} />
            <StatusBadge status={lic.status} />
          </div>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-white transition-colors"><X size={18} /></button>
        </div>

        {/* Full key */}
        <div className="bg-[#060B14] border border-white/8 rounded-lg px-4 py-3 flex items-center justify-between gap-3 mb-5">
          <p className="font-mono text-xs text-sky-400 break-all flex-1">{lic.key}</p>
          <button onClick={copyKey} className="shrink-0 text-[#94A3B8] hover:text-white transition-colors">
            {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
          </button>
        </div>

        {/* Details grid */}
        <div className="grid grid-cols-2 gap-3 mb-5">
          {[
            { label: "Email",      value: lic.email || "—" },
            { label: "Platform",   value: lic.platform || "—" },
            { label: "Activated",  value: fmtDate(lic.activated) },
            { label: "Heartbeat",  value: timeAgo(lic.last_heartbeat) },
          ].map(({ label, value }) => (
            <div key={label} className="bg-[#060B14] rounded-lg px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wider text-[#94A3B8] mb-1">{label}</p>
              <p className="text-sm text-white">{value}</p>
            </div>
          ))}
        </div>

        {/* Tier limits */}
        <div className="border border-white/8 rounded-lg p-4 mb-4">
          <p className="text-[10px] uppercase tracking-wider text-[#94A3B8] mb-3">Tier Limits — {cfg.label}</p>
          <div className="grid grid-cols-4 gap-3 mb-3">
            {[
              { label: "Keys",         value: cfg.maxKeys ?? "∞" },
              { label: "Projects",     value: cfg.maxProjects ?? "∞" },
              { label: "Devices",      value: cfg.maxDevices ?? "∞" },
              { label: "Agent Tokens", value: lic.agent_token_count != null ? `${lic.agent_token_count} active` : "—" },
            ].map(({ label, value }) => (
              <div key={label} className="text-center">
                <p className={`text-xl font-bold ${cfg.text}`}>{value}</p>
                <p className="text-[10px] text-[#94A3B8] uppercase tracking-wider mt-0.5">{label}</p>
              </div>
            ))}
          </div>
          {cfg.features.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-3 border-t border-white/8">
              {cfg.features.map(f => (
                <span key={f} className="text-[10px] bg-white/5 text-[#94A3B8] px-2 py-1 rounded">{f}</span>
              ))}
            </div>
          )}
        </div>

        {lic.notes && (
          <div className="bg-[#060B14] rounded-lg px-3 py-2.5 mb-4">
            <p className="text-[10px] uppercase tracking-wider text-[#94A3B8] mb-1">Notes</p>
            <p className="text-sm text-white">{lic.notes}</p>
          </div>
        )}

        <button onClick={onClose} className="w-full border border-white/10 text-[#94A3B8] text-sm py-2.5 rounded-lg hover:border-white/20 hover:text-white transition-colors">
          Close
        </button>
      </div>
    </div>
  )
}

// ── Generate Key Modal ───────────────────────────────────────────
function GenerateModal({ onClose, onCreated }: { onClose: () => void; onCreated: (l: License) => void }) {
  const { secret } = useAdmin()
  const [tier, setTier] = useState("pro")
  const [email, setEmail] = useState("")
  const [notes, setNotes] = useState("")
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState("")
  const [result, setResult] = useState<License | null>(null)
  const [copied, setCopied] = useState(false)

  async function submit() {
    setErr("")
    setLoading(true)
    try {
      const lic = await adminApi.generate(secret, { tier, email, notes })
      setResult(lic)
      onCreated(lic)
    } catch (e) {
      setErr(String(e))
    } finally {
      setLoading(false)
    }
  }

  function copyKey() {
    if (!result) return
    navigator.clipboard.writeText(result.key)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#0D1B2A] border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <p className="font-semibold text-white">Generate License Key</p>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-white transition-colors"><X size={18} /></button>
        </div>

        {result ? (
          <div className="space-y-4">
            <p className="text-sm text-[#94A3B8]">Key generated — copy it now, it won&apos;t be shown in full again.</p>
            <div className="bg-[#060B14] border border-[#00DC82]/30 rounded-lg px-4 py-3 flex items-center gap-3">
              <p className="font-mono text-sm text-[#00DC82] break-all flex-1">{result.key}</p>
              <button onClick={copyKey} className="shrink-0 text-[#94A3B8] hover:text-[#00DC82] transition-colors">
                {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
              </button>
            </div>
            <button onClick={onClose} className="w-full bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2.5 rounded-lg hover:bg-[#00DC82]/90 transition-colors">
              Done
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-[#94A3B8] uppercase tracking-wider">Tier</label>
              <select
                value={tier}
                onChange={e => setTier(e.target.value)}
                className="mt-1 w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white outline-none focus:border-[#00DC82]/50 transition-colors"
              >
                {Object.entries(TIER_CFG).map(([k, v]) => (
                  <option key={k} value={k}>{v.icon} {v.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-[#94A3B8] uppercase tracking-wider">Email (optional)</label>
              <input
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="user@example.com"
                className="mt-1 w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/40 outline-none focus:border-[#00DC82]/50 transition-colors"
              />
            </div>
            <div>
              <label className="text-xs text-[#94A3B8] uppercase tracking-wider">Notes (optional)</label>
              <textarea
                value={notes}
                onChange={e => setNotes(e.target.value)}
                rows={2}
                className="mt-1 w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/40 outline-none focus:border-[#00DC82]/50 transition-colors resize-none"
              />
            </div>
            {err && <p className="text-xs text-red-400">{err}</p>}
            <div className="flex gap-3 pt-1">
              <button onClick={onClose} className="flex-1 border border-white/10 text-[#94A3B8] text-sm py-2.5 rounded-lg hover:border-white/20 hover:text-white transition-colors">
                Cancel
              </button>
              <button onClick={submit} disabled={loading} className="flex-1 bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2.5 rounded-lg hover:bg-[#00DC82]/90 disabled:opacity-40 transition-colors">
                {loading ? "Generating…" : "Generate"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Action button ────────────────────────────────────────────────
function ActionBtn({ label, variant, onClick, loading }: {
  label: string; variant: "outline" | "amber" | "red" | "green"; onClick: () => void; loading?: boolean
}) {
  const styles = {
    outline: "border border-white/15 text-[#94A3B8] hover:text-white hover:border-white/30",
    amber:   "border border-amber-700/60 bg-amber-900/30 text-amber-300 hover:bg-amber-900/50",
    red:     "border border-red-700/60 bg-red-900/30 text-red-300 hover:bg-red-900/50",
    green:   "border border-emerald-700/60 bg-emerald-900/30 text-emerald-300 hover:bg-emerald-900/50",
  }
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`px-2.5 py-1 rounded text-xs font-medium transition-colors disabled:opacity-40 ${styles[variant]}`}
    >
      {loading ? "…" : label}
    </button>
  )
}

// ── Page buttons ─────────────────────────────────────────────────
function PageBtn({ label, icon, onClick, disabled, active }: {
  label?: string; icon?: React.ReactNode; onClick: () => void; disabled?: boolean; active?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`w-7 h-7 flex items-center justify-center rounded text-xs transition-colors disabled:opacity-30 ${
        active ? "bg-white/15 text-white" : "text-[#94A3B8] hover:text-white hover:bg-white/8"
      }`}
    >
      {icon ?? label}
    </button>
  )
}

// ── Issue Key Panel ──────────────────────────────────────────────
const SOURCES = ["Twitter", "ProductHunt", "Referral", "Direct", "Conference", "Other"]
const TRIAL_OPTIONS: { label: string; value: 7 | 14 | 30 | null }[] = [
  { label: "No expiry", value: null },
  { label: "7 days",    value: 7 },
  { label: "14 days",   value: 14 },
  { label: "30 days",   value: 30 },
]

function IssueKeyPanel({ onClose, onIssued }: { onClose: () => void; onIssued: () => void }) {
  const { secret } = useAdmin()
  const [form, setForm] = useState<IssueKeyRequest>({
    email: "", tier: "pro", name: "", company: "", source: "Direct",
    trial_days: 14, follow_up_date: "", notes: "", send_email: true,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState("")
  const [success, setSuccess] = useState("")

  function set<K extends keyof IssueKeyRequest>(k: K, v: IssueKeyRequest[K]) {
    setForm(f => ({ ...f, [k]: v }))
  }

  async function submit() {
    if (!form.email.trim()) { setError("Email is required"); return }
    setLoading(true); setError("")
    try {
      const res = await adminApi.issueKey(secret, form)
      const emailMsg = res.email_result.sent
        ? " Invite sent."
        : res.email_result.reason === "smtp_not_configured"
        ? " (SMTP not configured — key generated only)"
        : ` (Email failed: ${res.email_result.reason})`
      setSuccess(`Key issued: ${res.key.slice(0, 12)}…${emailMsg}`)
      onIssued()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }

  const inputCls = "w-full bg-[#060B14] border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-[#475569] focus:outline-none focus:border-[#7C3AED]/60"
  const labelCls = "text-[10px] uppercase tracking-wider text-[#94A3B8] mb-1 block"

  return (
    <div className="w-80 shrink-0 border-l border-white/8 bg-[#0D1B2A] flex flex-col">
      <div className="flex items-center justify-between px-5 py-4 border-b border-white/8">
        <span className="text-sm font-bold text-white">Issue New Key</span>
        <button onClick={onClose} className="text-[#94A3B8] hover:text-white"><X size={16} /></button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        <div>
          <label className={labelCls}>Email *</label>
          <input className={inputCls} placeholder="sarah@acme.com" value={form.email}
            onChange={e => set("email", e.target.value)} />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>Name</label>
            <input className={inputCls} placeholder="Sarah Chen" value={form.name ?? ""}
              onChange={e => set("name", e.target.value)} />
          </div>
          <div>
            <label className={labelCls}>Company</label>
            <input className={inputCls} placeholder="Acme Corp" value={form.company ?? ""}
              onChange={e => set("company", e.target.value)} />
          </div>
        </div>

        <div>
          <label className={labelCls}>Tier *</label>
          <select className={inputCls} value={form.tier}
            onChange={e => set("tier", e.target.value as IssueKeyRequest["tier"])}>
            {(["free","starter","pro","team","enterprise"] as const).map(t => (
              <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>Trial Duration</label>
            <select className={inputCls} value={form.trial_days === null ? "null" : String(form.trial_days)}
              onChange={e => {
                const v = e.target.value
                set("trial_days", v === "null" ? null : Number(v) as 7 | 14 | 30)
              }}>
              {TRIAL_OPTIONS.map(o => (
                <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls}>Source</label>
            <select className={inputCls} value={form.source ?? "Direct"}
              onChange={e => set("source", e.target.value)}>
              {SOURCES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>

        <div>
          <label className={labelCls}>Follow-up Date</label>
          <input type="date" className={inputCls} value={form.follow_up_date ?? ""}
            onChange={e => set("follow_up_date", e.target.value)} />
        </div>

        <div>
          <label className={labelCls}>Notes</label>
          <textarea className={`${inputCls} h-20 resize-none`} placeholder="Met at NYC meetup…"
            value={form.notes ?? ""} onChange={e => set("notes", e.target.value)} />
        </div>

        <div className="bg-[#060B14] rounded-lg p-3 border border-white/6">
          <label className={labelCls}>Send email?</label>
          <div className="flex gap-2">
            <button
              onClick={() => set("send_email", true)}
              className={`flex-1 text-xs py-2 rounded-md border transition-colors ${form.send_email ? "bg-[#7C3AED]/20 border-[#7C3AED]/60 text-violet-300" : "border-white/10 text-[#94A3B8]"}`}>
              ✉ Send invite
            </button>
            <button
              onClick={() => set("send_email", false)}
              className={`flex-1 text-xs py-2 rounded-md border transition-colors ${!form.send_email ? "bg-white/8 border-white/20 text-white" : "border-white/10 text-[#94A3B8]"}`}>
              Generate only
            </button>
          </div>
        </div>

        {error   && <p className="text-xs text-red-400">{error}</p>}
        {success && <p className="text-xs text-emerald-400">{success}</p>}
      </div>

      <div className="px-5 py-4 border-t border-white/8">
        <button
          onClick={submit}
          disabled={loading}
          className="w-full bg-[#7C3AED] hover:bg-[#6D28D9] disabled:opacity-50 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors">
          {loading ? "Issuing…" : "Issue Key →"}
        </button>
      </div>
    </div>
  )
}

// ── Inner page (uses useSearchParams — must be inside Suspense) ──
const TIER_TABS = ["All", "Free", "Starter", "Pro", "Team", "Ent", "Revoked"] as const
const PAGE_SIZE = 10

function LicensesInner() {
  const { secret, stats, refreshStats } = useAdmin()
  const searchParams = useSearchParams()

  const [licenses, setLicenses] = useState<License[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [activeTab, setActiveTab] = useState<string>(() => {
    const t = searchParams.get("tier")
    return t === "revoked" ? "Revoked" : "All"
  })
  const [page, setPage] = useState(1)
  const [showGenerate, setShowGenerate] = useState(searchParams.get("generate") === "1")
  const [viewLic, setViewLic] = useState<License | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [showIssuePanel, setShowIssuePanel] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)

  const load = useCallback(() => {
    if (!secret) return
    setLoading(true)
    adminApi.licenses(secret)
      .then(setLicenses)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [secret])

  useEffect(() => { load() }, [load])

  const filtered = useMemo(() => {
    let list = licenses
    if (activeTab !== "All") {
      if (activeTab === "Revoked") {
        list = list.filter(l => l.status === "revoked")
      } else {
        const t = activeTab.toLowerCase() === "ent" ? "enterprise" : activeTab.toLowerCase()
        list = list.filter(l => l.tier === t)
      }
    }
    if (search) {
      const q = search.toLowerCase()
      list = list.filter(l =>
        l.key.toLowerCase().includes(q) ||
        l.email.toLowerCase().includes(q) ||
        l.tier.includes(q) ||
        l.platform.toLowerCase().includes(q) ||
        l.status.includes(q),
      )
    }
    return list
  }, [licenses, activeTab, search])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const pageData = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  // Smart pagination: show window of 5 around current page
  const pageNums = useMemo(() => {
    const total = totalPages
    const cur = safePage
    if (total <= 5) return Array.from({ length: total }, (_, i) => i + 1)
    const start = Math.max(1, Math.min(cur - 2, total - 4))
    return Array.from({ length: 5 }, (_, i) => start + i)
  }, [totalPages, safePage])

  async function withAction(key: string, tag: string, fn: () => Promise<void>) {
    setActionLoading(key + ":" + tag)
    try { await fn(); load(); refreshStats() }
    finally { setActionLoading(null) }
  }

  function changeTab(t: string) { setActiveTab(t); setPage(1) }
  function changeSearch(v: string) { setSearch(v); setPage(1) }

  return (
    <div className="p-8">
      {showGenerate && (
        <GenerateModal onClose={() => setShowGenerate(false)} onCreated={() => { load(); refreshStats() }} />
      )}
      {viewLic && <ViewModal lic={viewLic} onClose={() => setViewLic(null)} />}

      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-xl font-bold text-white">
          License Activations{" "}
          <span className="text-[#94A3B8] font-normal text-base">{filtered.length} shown</span>
        </h1>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input
              value={search}
              onChange={e => changeSearch(e.target.value)}
              placeholder="Search key, tier, platform…"
              className="bg-[#0D1B2A] border border-white/8 rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder:text-[#94A3B8]/50 outline-none focus:border-white/20 w-56 transition-colors"
            />
          </div>
          <button
            onClick={() => adminApi.exportCsv(secret, {
              tier:   activeTab === "Revoked" ? undefined : activeTab,
              status: activeTab === "Revoked" ? "revoked" : undefined,
              search: search || undefined,
            }).catch(() => {})}
            className="flex items-center gap-2 border border-white/10 text-[#94A3B8] text-sm px-3.5 py-2 rounded-lg hover:border-white/20 hover:text-white transition-colors"
          >
            <Download size={14} /> Export CSV
          </button>
          <button
            onClick={() => setShowGenerate(true)}
            className="flex items-center gap-2 bg-[#00DC82] text-[#060B14] font-semibold text-sm px-4 py-2 rounded-lg hover:bg-[#00DC82]/90 transition-colors"
          >
            <Plus size={14} /> Generate Key
          </button>
          <button
            onClick={() => setShowIssuePanel(p => !p)}
            className="flex items-center gap-2 bg-[#7C3AED] hover:bg-[#6D28D9] text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors">
            <Plus size={15} />
            Issue Key
          </button>
        </div>
      </div>

      {/* Stat cards */}
      <div className="flex gap-4 mb-8">
        <StatCard label="Total Active" value={stats?.total_active ?? 0} sub={`↑ ${stats?.week_delta ?? 0} this week`} accent="bg-emerald-500" />
        <StatCard
          label="New Today"
          value={stats?.new_today ?? 0}
          sub={`${(stats?.today_delta ?? 0) >= 0 ? "↑" : "↓"} ${Math.abs(stats?.today_delta ?? 0)} vs yesterday`}
          accent="bg-sky-500"
        />
        <StatCard
          label="Pro + Team"
          value={stats?.pro_team ?? 0}
          sub={stats?.total_active ? `${Math.round((stats.pro_team / stats.total_active) * 100)}% of total` : "—"}
          accent="bg-violet-500"
        />
        <StatCard label="Revoked" value={stats?.revoked ?? 0} sub={`${stats?.revoked ?? 0} total revoked`} accent="bg-red-500" />
      </div>

      {/* Table + Issue Panel */}
      <div className="flex flex-1 min-h-0">
      <div className="flex-1 overflow-auto">
      <div className="bg-[#0D1B2A] border border-white/8 rounded-xl overflow-hidden">
        {/* Filter tabs */}
        <div className="flex items-center gap-1 px-5 pt-4 pb-3 border-b border-white/8">
          <p className="font-semibold text-white mr-4">All Activations</p>
          <div className="ml-auto flex gap-1 flex-wrap">
            {TIER_TABS.map(t => (
              <button
                key={t}
                onClick={() => changeTab(t)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  activeTab === t ? "bg-white/10 text-white" : "text-[#94A3B8] hover:text-white hover:bg-white/5"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Bulk action bar (shows when selection > 0) */}
        {selected.size > 0 && (
          <div className="flex items-center gap-3 px-5 py-3 border-b border-white/8 bg-sky-900/20">
            <span className="text-sm text-white font-medium">{selected.size} selected</span>
            <div className="ml-auto flex items-center gap-2">
              <button
                disabled={bulkBusy}
                onClick={async () => {
                  if (!confirm(`Expire ${selected.size} license(s)?`)) return
                  setBulkBusy(true)
                  try { await adminApi.bulkAction(secret, "expire", Array.from(selected)); setSelected(new Set()); load(); refreshStats() }
                  finally { setBulkBusy(false) }
                }}
                className="text-xs border border-amber-700/60 bg-amber-900/30 text-amber-300 hover:bg-amber-900/50 disabled:opacity-40 px-3 py-1.5 rounded transition-colors"
              >Bulk Expire</button>
              <button
                disabled={bulkBusy}
                onClick={async () => {
                  if (!confirm(`Revoke ${selected.size} license(s)? This cannot be undone via UI.`)) return
                  setBulkBusy(true)
                  try { await adminApi.bulkAction(secret, "revoke", Array.from(selected)); setSelected(new Set()); load(); refreshStats() }
                  finally { setBulkBusy(false) }
                }}
                className="text-xs border border-red-700/60 bg-red-900/30 text-red-300 hover:bg-red-900/50 disabled:opacity-40 px-3 py-1.5 rounded transition-colors"
              >Bulk Revoke</button>
              <button
                disabled={bulkBusy}
                onClick={async () => {
                  setBulkBusy(true)
                  try { await adminApi.bulkAction(secret, "renew", Array.from(selected)); setSelected(new Set()); load(); refreshStats() }
                  finally { setBulkBusy(false) }
                }}
                className="text-xs border border-emerald-700/60 bg-emerald-900/30 text-emerald-300 hover:bg-emerald-900/50 disabled:opacity-40 px-3 py-1.5 rounded transition-colors"
              >Bulk Renew</button>
              <button
                onClick={() => setSelected(new Set())}
                className="text-xs border border-white/10 text-[#94A3B8] hover:text-white px-3 py-1.5 rounded transition-colors"
              >Clear</button>
            </div>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/8">
                <th className="px-3 py-3 w-10">
                  <input
                    type="checkbox"
                    className="w-4 h-4 accent-[#00DC82] cursor-pointer"
                    checked={pageData.length > 0 && pageData.every(l => selected.has(l.key))}
                    onChange={e => {
                      const next = new Set(selected)
                      if (e.target.checked) pageData.forEach(l => next.add(l.key))
                      else pageData.forEach(l => next.delete(l.key))
                      setSelected(next)
                    }}
                  />
                </th>
                {["License Key", "Tier", "Platform", "Activated", "Last Heartbeat", "Expires", "Status", "Actions"].map(h => (
                  <th key={h} className="px-5 py-3 text-left text-[10px] tracking-widest uppercase text-[#94A3B8] font-medium whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9} className="px-5 py-12 text-center text-[#94A3B8]">Loading…</td></tr>
              ) : pageData.length === 0 ? (
                <tr><td colSpan={9} className="px-5 py-12 text-center text-[#94A3B8]">No licenses found</td></tr>
              ) : pageData.map(lic => (
                <tr key={lic.key} className={`border-b border-white/5 transition-colors ${selected.has(lic.key) ? "bg-sky-900/10" : "hover:bg-white/[0.03]"}`}>
                  <td className="px-3 py-4">
                    <input
                      type="checkbox"
                      className="w-4 h-4 accent-[#00DC82] cursor-pointer"
                      checked={selected.has(lic.key)}
                      onChange={e => {
                        const next = new Set(selected)
                        if (e.target.checked) next.add(lic.key); else next.delete(lic.key)
                        setSelected(next)
                      }}
                    />
                  </td>
                  <td className="px-5 py-4 whitespace-nowrap">
                    <p className="font-mono text-sm text-sky-400">{maskKey(lic.key)}</p>
                    {(lic.name || lic.company) && (
                      <p className="text-[10px] text-[#64748B] mt-0.5">
                        {[lic.name, lic.company].filter(Boolean).join(" · ")}
                      </p>
                    )}
                  </td>
                  <td className="px-5 py-4"><TierBadge tier={lic.tier} /></td>
                  <td className="px-5 py-4"><PlatformCell platform={lic.platform} /></td>
                  <td className="px-5 py-4 text-[#94A3B8] whitespace-nowrap">{fmtDate(lic.activated)}</td>
                  <td className="px-5 py-4 text-[#94A3B8] whitespace-nowrap">{timeAgo(lic.last_heartbeat)}</td>
                  <td className="px-4 py-3 text-sm whitespace-nowrap">
                    {lic.expires_at ? (
                      <span className={
                        lic.expires_at < new Date().toISOString()
                          ? "text-red-400"
                          : isExpiringSoon(lic.expires_at)
                          ? "text-amber-400"
                          : "text-[#94A3B8]"
                      }>
                        {fmtDateOrDash(lic.expires_at)}
                      </span>
                    ) : (
                      <span className="text-[#475569]">—</span>
                    )}
                  </td>
                  <td className="px-5 py-4"><StatusBadge status={lic.status} /></td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-1.5">
                      <ActionBtn label="View" variant="outline" onClick={() => setViewLic(lic)} />
                      {lic.status === "active" && (
                        <ActionBtn
                          label="Expire"
                          variant="amber"
                          loading={actionLoading === lic.key + ":expire"}
                          onClick={() => withAction(lic.key, "expire", () => adminApi.expire(secret, lic.key))}
                        />
                      )}
                      {lic.status === "expired" && (
                        <ActionBtn
                          label="Renew"
                          variant="green"
                          loading={actionLoading === lic.key + ":renew"}
                          onClick={() => withAction(lic.key, "renew", () => adminApi.renew(secret, lic.key))}
                        />
                      )}
                      {lic.status !== "revoked" && (
                        <ActionBtn
                          label="Revoke"
                          variant="red"
                          loading={actionLoading === lic.key + ":revoke"}
                          onClick={() => withAction(lic.key, "revoke", () => adminApi.revoke(secret, lic.key))}
                        />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-white/8">
          <p className="text-xs text-[#94A3B8]">
            {filtered.length === 0 ? "No results" : `Showing ${(safePage - 1) * PAGE_SIZE + 1}–${Math.min(safePage * PAGE_SIZE, filtered.length)} of ${filtered.length}`}
          </p>
          <div className="flex items-center gap-1">
            <PageBtn icon={<ChevronLeft size={14} />} onClick={() => setPage(p => Math.max(1, p - 1))} disabled={safePage === 1} />
            {pageNums[0] > 1 && <span className="text-[#94A3B8] text-xs px-1">…</span>}
            {pageNums.map(n => (
              <PageBtn key={n} label={String(n)} onClick={() => setPage(n)} active={safePage === n} />
            ))}
            {pageNums[pageNums.length - 1] < totalPages && <span className="text-[#94A3B8] text-xs px-1">…</span>}
            <PageBtn icon={<ChevronRight size={14} />} onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={safePage === totalPages} />
          </div>
        </div>
      </div>
      </div>{/* flex-1 overflow-auto */}
      {showIssuePanel && (
        <IssueKeyPanel
          onClose={() => setShowIssuePanel(false)}
          onIssued={() => { setShowIssuePanel(false); load(); refreshStats() }}
        />
      )}
      </div>{/* flex flex-1 min-h-0 */}
    </div>
  )
}

// ── Export with Suspense boundary ────────────────────────────────
export default function LicensesPage() {
  return (
    <Suspense fallback={<div className="p-8 text-[#94A3B8]">Loading…</div>}>
      <LicensesInner />
    </Suspense>
  )
}
