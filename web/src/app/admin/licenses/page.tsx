"use client"
import { useEffect, useState, useMemo } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { Search, Download, Plus, ChevronLeft, ChevronRight, X } from "lucide-react"
import { adminApi, maskKey, timeAgo, fmtDate, type License } from "@/lib/admin-api"
import { useAdmin } from "../_context"

// ── Tier badge ───────────────────────────────────────────────────
const TIER_CFG = {
  free:       { label: "Free",       icon: "🔲", bg: "bg-sky-900/40",    text: "text-sky-300",   border: "border-sky-800/60" },
  starter:    { label: "Starter",    icon: "🚀", bg: "bg-violet-900/40", text: "text-violet-300", border: "border-violet-800/60" },
  pro:        { label: "Pro",        icon: "⚡", bg: "bg-purple-900/50", text: "text-purple-200", border: "border-purple-700/60" },
  team:       { label: "Team",       icon: "👥", bg: "bg-teal-900/40",   text: "text-teal-300",  border: "border-teal-800/60" },
  enterprise: { label: "Enterprise", icon: "🏛️", bg: "bg-amber-900/40",  text: "text-amber-300", border: "border-amber-800/60" },
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

// ── Platform icon ────────────────────────────────────────────────
function PlatformCell({ platform }: { platform: string }) {
  const p = platform.toLowerCase()
  const icon = p.includes("mac") ? "🍎" : p.includes("linux") ? "🐧" : "🪟"
  return (
    <span className="inline-flex items-center gap-2 text-sm text-[#94A3B8]">
      {icon} {platform || "—"}
    </span>
  )
}

// ── Stat card ────────────────────────────────────────────────────
function StatCard({
  label, value, sub, accent,
}: { label: string; value: number; sub: string; accent: string }) {
  return (
    <div className={`relative bg-[#0D1B2A] border border-white/8 rounded-xl p-5 overflow-hidden flex-1 min-w-0`}>
      <div className={`absolute left-0 top-0 bottom-0 w-1 rounded-l-xl ${accent}`} />
      <p className="text-[10px] tracking-widest uppercase text-[#94A3B8] mb-2">{label}</p>
      <p className="text-3xl font-bold text-white">{value.toLocaleString()}</p>
      <p className="text-xs text-[#94A3B8] mt-1">{sub}</p>
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#0D1B2A] border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <p className="font-semibold text-white">Generate License Key</p>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-white">
            <X size={18} />
          </button>
        </div>

        {result ? (
          <div className="space-y-4">
            <p className="text-sm text-[#94A3B8]">Key generated successfully:</p>
            <div className="bg-[#060B14] border border-[#00DC82]/30 rounded-lg px-4 py-3">
              <p className="font-mono text-sm text-[#00DC82] break-all">{result.key}</p>
            </div>
            <p className="text-xs text-[#94A3B8]">Copy this key now — it cannot be recovered in full later.</p>
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
                className="mt-1 w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white outline-none focus:border-[#00DC82]/50"
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
              <button
                onClick={onClose}
                className="flex-1 border border-white/10 text-[#94A3B8] text-sm py-2.5 rounded-lg hover:border-white/20 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={submit}
                disabled={loading}
                className="flex-1 bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2.5 rounded-lg hover:bg-[#00DC82]/90 disabled:opacity-40 transition-colors"
              >
                {loading ? "Generating…" : "Generate"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────
const TIERS = ["All", "Free", "Starter", "Pro", "Team", "Ent"] as const
const PAGE_SIZE = 10

export default function LicensesPage() {
  const { secret, stats, refreshStats } = useAdmin()
  const searchParams = useSearchParams()
  const router = useRouter()
  const [licenses, setLicenses] = useState<License[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [tierFilter, setTierFilter] = useState<string>(
    searchParams.get("tier") === "revoked" ? "All" : "All"
  )
  const [statusFilter] = useState<string | null>(
    searchParams.get("tier") === "revoked" ? "revoked" : null
  )
  const [page, setPage] = useState(1)
  const [showGenerate, setShowGenerate] = useState(searchParams.get("generate") === "1")
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    adminApi.licenses(secret)
      .then(setLicenses)
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { if (secret) load() }, [secret])

  const filtered = useMemo(() => {
    let list = licenses
    if (statusFilter) {
      list = list.filter(l => l.status === statusFilter)
    } else if (tierFilter !== "All") {
      const t = tierFilter.toLowerCase() === "ent" ? "enterprise" : tierFilter.toLowerCase()
      list = list.filter(l => l.tier === t)
    }
    if (search) {
      const q = search.toLowerCase()
      list = list.filter(l =>
        l.key.toLowerCase().includes(q) ||
        l.email.toLowerCase().includes(q) ||
        l.tier.includes(q) ||
        l.platform.toLowerCase().includes(q),
      )
    }
    return list
  }, [licenses, tierFilter, statusFilter, search])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageData = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  async function action(fn: () => Promise<void>) {
    await fn()
    load()
    refreshStats()
  }

  async function doExpire(key: string) {
    setActionLoading(key + ":expire")
    await action(() => adminApi.expire(secret, key)).finally(() => setActionLoading(null))
  }
  async function doRevoke(key: string) {
    setActionLoading(key + ":revoke")
    await action(() => adminApi.revoke(secret, key)).finally(() => setActionLoading(null))
  }
  async function doRenew(key: string) {
    setActionLoading(key + ":renew")
    await action(() => adminApi.renew(secret, key)).finally(() => setActionLoading(null))
  }

  return (
    <div className="p-8">
      {showGenerate && (
        <GenerateModal
          onClose={() => setShowGenerate(false)}
          onCreated={() => { load(); refreshStats() }}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-xl font-bold text-white">
            License Activations{" "}
            <span className="text-[#94A3B8] font-normal text-base">{filtered.length} shown</span>
          </h1>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
            <input
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1) }}
              placeholder="Search key, tier, platform…"
              className="bg-[#0D1B2A] border border-white/8 rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder:text-[#94A3B8]/50 outline-none focus:border-white/20 w-56 transition-colors"
            />
          </div>
          <button
            onClick={() => adminApi.exportCsv(secret)}
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
        </div>
      </div>

      {/* Stat cards */}
      <div className="flex gap-4 mb-8">
        <StatCard
          label="Total Active"
          value={stats?.total_active ?? 0}
          sub={`↑ ${stats?.week_delta ?? 0} this week`}
          accent="bg-emerald-500"
        />
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
        <StatCard
          label="Revoked"
          value={stats?.revoked ?? 0}
          sub={`${stats?.revoked ?? 0} this month`}
          accent="bg-red-500"
        />
      </div>

      {/* Table card */}
      <div className="bg-[#0D1B2A] border border-white/8 rounded-xl overflow-hidden">
        {/* Tier filter tabs */}
        <div className="flex items-center gap-1 px-5 pt-4 pb-3 border-b border-white/8">
          <p className="font-semibold text-white mr-4">All Activations</p>
          <div className="ml-auto flex gap-1">
            {TIERS.map(t => (
              <button
                key={t}
                onClick={() => { setTierFilter(t); setPage(1) }}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  tierFilter === t
                    ? "bg-white/10 text-white"
                    : "text-[#94A3B8] hover:text-white"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/8">
                {["License Key", "Tier", "Platform", "Activated", "Last Heartbeat", "Status", "Actions"].map(h => (
                  <th key={h} className="px-5 py-3 text-left text-[10px] tracking-widest uppercase text-[#94A3B8] font-medium whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center text-[#94A3B8]">Loading…</td>
                </tr>
              ) : pageData.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center text-[#94A3B8]">No licenses found</td>
                </tr>
              ) : pageData.map(lic => (
                <tr key={lic.key} className="border-b border-white/5 hover:bg-white/3 transition-colors">
                  <td className="px-5 py-4 font-mono text-sm text-sky-400 whitespace-nowrap">
                    {maskKey(lic.key)}
                  </td>
                  <td className="px-5 py-4"><TierBadge tier={lic.tier} /></td>
                  <td className="px-5 py-4"><PlatformCell platform={lic.platform} /></td>
                  <td className="px-5 py-4 text-[#94A3B8] whitespace-nowrap">{fmtDate(lic.activated)}</td>
                  <td className="px-5 py-4 text-[#94A3B8] whitespace-nowrap">{timeAgo(lic.last_heartbeat)}</td>
                  <td className="px-5 py-4"><StatusBadge status={lic.status} /></td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-1.5">
                      <ActionBtn
                        label="View"
                        variant="outline"
                        onClick={() => alert(`Key: ${lic.key}\nEmail: ${lic.email}\nNotes: ${lic.notes || "—"}`)}
                      />
                      {lic.status === "expired" ? (
                        <ActionBtn
                          label={actionLoading === lic.key + ":renew" ? "…" : "Renew"}
                          variant="green"
                          onClick={() => doRenew(lic.key)}
                        />
                      ) : lic.status === "active" ? (
                        <ActionBtn
                          label={actionLoading === lic.key + ":expire" ? "…" : "Expire"}
                          variant="amber"
                          onClick={() => doExpire(lic.key)}
                        />
                      ) : null}
                      {lic.status !== "revoked" && (
                        <ActionBtn
                          label={actionLoading === lic.key + ":revoke" ? "…" : "Revoke"}
                          variant="red"
                          onClick={() => doRevoke(lic.key)}
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
            Showing {Math.min((page - 1) * PAGE_SIZE + 1, filtered.length)}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length}
          </p>
          <div className="flex items-center gap-1">
            <PageBtn icon={<ChevronLeft size={14} />} onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} />
            {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => i + 1).map(n => (
              <PageBtn key={n} label={String(n)} onClick={() => setPage(n)} active={page === n} />
            ))}
            <PageBtn icon={<ChevronRight size={14} />} onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages} />
          </div>
        </div>
      </div>
    </div>
  )
}

function ActionBtn({
  label, variant, onClick, icon,
}: {
  label?: string; variant: "outline" | "amber" | "red" | "green"; onClick: () => void; icon?: React.ReactNode
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
      className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${styles[variant]}`}
    >
      {icon}{label}
    </button>
  )
}

function PageBtn({
  label, icon, onClick, disabled, active,
}: {
  label?: string; icon?: React.ReactNode; onClick: () => void; disabled?: boolean; active?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`w-7 h-7 flex items-center justify-center rounded text-xs transition-colors disabled:opacity-30 ${
        active
          ? "bg-white/15 text-white"
          : "text-[#94A3B8] hover:text-white hover:bg-white/8"
      }`}
    >
      {icon ?? label}
    </button>
  )
}
