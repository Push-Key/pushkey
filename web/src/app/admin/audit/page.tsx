"use client"
import { useEffect, useMemo, useState } from "react"
import { ShieldCheck, Filter, RefreshCw } from "lucide-react"
import { adminApi, type AuditEntry } from "@/lib/admin-api"
import { useAdmin } from "../_context"

const ACTION_LABELS: Record<string, { label: string; color: string }> = {
  generate_license: { label: "Generated",   color: "text-emerald-300 bg-emerald-900/30 border-emerald-800/40" },
  issue_license:    { label: "Issued",      color: "text-emerald-300 bg-emerald-900/30 border-emerald-800/40" },
  expire_license:   { label: "Expired",     color: "text-amber-300 bg-amber-900/30 border-amber-800/40" },
  revoke_license:   { label: "Revoked",     color: "text-red-300 bg-red-900/30 border-red-800/40" },
  renew_license:    { label: "Renewed",     color: "text-emerald-300 bg-emerald-900/30 border-emerald-800/40" },
  send_invite:      { label: "Sent Invite", color: "text-sky-300 bg-sky-900/30 border-sky-800/40" },
  update_contact:   { label: "Edit",        color: "text-violet-300 bg-violet-900/30 border-violet-800/40" },
  bulk_expire:      { label: "Bulk Expire", color: "text-amber-300 bg-amber-900/30 border-amber-800/40" },
  bulk_revoke:      { label: "Bulk Revoke", color: "text-red-300 bg-red-900/30 border-red-800/40" },
  bulk_renew:       { label: "Bulk Renew",  color: "text-emerald-300 bg-emerald-900/30 border-emerald-800/40" },
}

function actionConfig(action: string) {
  return ACTION_LABELS[action] ?? { label: action, color: "text-[#94A3B8] bg-white/5 border-white/10" }
}

function fmtTime(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", second: "2-digit",
  })
}

function maskKey(k: string) {
  if (!k.includes("-")) return k
  const p = k.split("-")
  if (p.length < 4) return k
  return `${p[0]}-${p[1]}-•••-${p[p.length - 1]}`
}

export default function AuditPage() {
  const { secret } = useAdmin()
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter]   = useState<string>("All")
  const [search, setSearch]   = useState("")

  function load() {
    if (!secret) return
    setLoading(true)
    adminApi.audit(secret)
      .then(setEntries)
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [secret])

  const filterOptions = useMemo(() => {
    const set = new Set(entries.map(e => e.action))
    return ["All", ...Array.from(set).sort()]
  }, [entries])

  const filtered = useMemo(() => {
    let list = entries
    if (filter !== "All") list = list.filter(e => e.action === filter)
    if (search) {
      const q = search.toLowerCase()
      list = list.filter(e =>
        e.target.toLowerCase().includes(q) ||
        e.action.toLowerCase().includes(q) ||
        JSON.stringify(e.details).toLowerCase().includes(q),
      )
    }
    return list
  }, [entries, filter, search])

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <ShieldCheck size={18} className="text-[#00DC82]" />
            Audit Log <span className="text-[#94A3B8] font-normal text-base">{filtered.length} entries</span>
          </h1>
          <p className="text-sm text-[#94A3B8] mt-1">Every admin action recorded for compliance — last 500 events</p>
        </div>
        <div className="flex items-center gap-3">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search target, action, details…"
            className="bg-[#0D1B2A] border border-white/8 rounded-lg px-3 py-2 text-sm text-white placeholder:text-[#94A3B8]/50 outline-none focus:border-white/20 w-64 transition-colors"
          />
          <select
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="bg-[#0D1B2A] border border-white/8 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-white/20 transition-colors"
          >
            {filterOptions.map(f => <option key={f} value={f}>{actionConfig(f).label || f}</option>)}
          </select>
          <button
            onClick={load}
            className="border border-white/10 text-[#94A3B8] hover:text-white hover:border-white/20 px-3 py-2 rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      <div className="bg-[#0D1B2A] border border-white/8 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/8">
                {["Timestamp", "Action", "Target", "Details"].map(h => (
                  <th key={h} className="px-5 py-3 text-left text-[10px] tracking-widest uppercase text-[#94A3B8] font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={4} className="px-5 py-12 text-center text-[#94A3B8]">Loading audit log…</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={4} className="px-5 py-16 text-center">
                  <Filter size={28} className="mx-auto mb-3 text-[#94A3B8]/30" />
                  <p className="text-[#94A3B8] text-sm">No audit entries</p>
                  <p className="text-[#94A3B8]/60 text-xs mt-1">Admin actions will appear here as they occur</p>
                </td></tr>
              ) : filtered.map((e, i) => {
                const cfg = actionConfig(e.action)
                return (
                  <tr key={i} className="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
                    <td className="px-5 py-3 text-xs text-[#94A3B8] font-mono whitespace-nowrap">{fmtTime(e.ts)}</td>
                    <td className="px-5 py-3">
                      <span className={`text-xs font-medium px-2 py-1 rounded-full border ${cfg.color}`}>
                        {cfg.label}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-xs font-mono text-sky-400">{maskKey(e.target)}</td>
                    <td className="px-5 py-3 text-xs text-[#94A3B8]">
                      {Object.keys(e.details).length === 0 ? "—" : (
                        <code className="text-[#94A3B8] text-[11px]">{JSON.stringify(e.details)}</code>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
