"use client"
import { useEffect, useState, useCallback } from "react"
import { Users, Mail } from "lucide-react"
import { adminApi, type Contact, type ContactKey, maskKey, fmtDateOrDash, isOverdue } from "@/lib/admin-api"
import { useAdmin } from "../_context"

const STAGE_CFG: Record<string, { label: string; dot: string; text: string; bg: string; border: string }> = {
  trial:     { label: "Trial",     dot: "bg-violet-400",  text: "text-violet-300",  bg: "bg-violet-900/30",  border: "border-violet-700/50" },
  active:    { label: "Active",    dot: "bg-emerald-400", text: "text-emerald-300", bg: "bg-emerald-900/20", border: "border-emerald-700/40" },
  converted: { label: "Converted", dot: "bg-emerald-400", text: "text-emerald-300", bg: "bg-emerald-900/20", border: "border-emerald-700/40" },
  churned:   { label: "Churned",   dot: "bg-slate-400",   text: "text-slate-400",   bg: "bg-slate-800/30",   border: "border-slate-700/40" },
  cold:      { label: "Cold",      dot: "bg-slate-500",   text: "text-slate-500",   bg: "bg-slate-900/20",   border: "border-slate-700/30" },
  "":        { label: "Unknown",   dot: "bg-slate-500",   text: "text-slate-400",   bg: "bg-slate-900/20",   border: "border-slate-700/30" },
}

const TIER_ICONS: Record<string, string> = {
  free: "🔲", starter: "🚀", pro: "⚡", team: "👥", enterprise: "🏛️",
}

function StageBadge({ stage }: { stage: string }) {
  const c = STAGE_CFG[stage] ?? STAGE_CFG[""]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${c.bg} ${c.text} ${c.border}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
      {c.label}
    </span>
  )
}

function KeyHistory({ keys }: { keys: ContactKey[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {keys.map(k => (
        <div key={k.key} className="bg-[#060B14] rounded-md px-2.5 py-1.5 border border-white/6 text-xs flex items-center gap-2">
          <span>{TIER_ICONS[k.tier] ?? "🔑"}</span>
          <span className="font-mono text-sky-400">{maskKey(k.key)}</span>
          <span className="text-[#475569]">·</span>
          <span className={k.status === "active" ? "text-emerald-400" : k.status === "revoked" ? "text-red-400" : "text-amber-400"}>
            {k.status}
          </span>
          {k.expires_at && (
            <>
              <span className="text-[#475569]">·</span>
              <span className={k.expires_at < new Date().toISOString() ? "text-red-400" : "text-[#94A3B8]"}>
                exp {fmtDateOrDash(k.expires_at)}
              </span>
            </>
          )}
        </div>
      ))}
    </div>
  )
}

function ContactCard({ contact, secret, onUpdated }: { contact: Contact; secret: string; onUpdated: () => void }) {
  const [editStage, setEditStage] = useState(false)
  const [stage, setStage]         = useState(contact.stage)
  const [expanded, setExpanded]   = useState(false)
  const overdue  = isOverdue(contact.follow_up_date)
  const initial  = (contact.name || contact.email).charAt(0).toUpperCase()
  const borderColor = overdue ? "border-amber-600/50" : stage === "converted" ? "border-emerald-700/40" : "border-white/8"
  const leftBar     = overdue ? "bg-amber-500"        : stage === "converted" ? "bg-emerald-500"        : "bg-[#1E293B]"

  async function saveStage(s: string) {
    await adminApi.updateContact(secret, contact.email, { stage: s })
    setStage(s)
    setEditStage(false)
    onUpdated()
  }

  return (
    <div className={`bg-[#0D1B2A] border ${borderColor} rounded-xl overflow-hidden`}>
      <div className="flex">
        <div className={`w-1 shrink-0 ${leftBar}`} />
        <div className="flex-1 p-4">
          {/* Header */}
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-[#1E293B] flex items-center justify-center text-sm font-bold text-[#94A3B8] shrink-0">
                {initial}
              </div>
              <div>
                <p className="text-sm font-semibold text-white">{contact.name || contact.email}</p>
                <p className="text-xs text-[#64748B]">
                  {contact.email}{contact.company ? ` · ${contact.company}` : ""}
                </p>
                {contact.source && (
                  <p className="text-[10px] text-[#475569] mt-0.5">Source: {contact.source}</p>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {overdue && contact.follow_up_date && (
                <span className="bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[10px] font-semibold px-2 py-1 rounded-full">
                  ⚠ Follow-up {fmtDateOrDash(contact.follow_up_date)}
                </span>
              )}
              {editStage ? (
                <select
                  autoFocus
                  value={stage}
                  onChange={e => saveStage(e.target.value)}
                  onBlur={() => setEditStage(false)}
                  className="text-xs bg-[#060B14] border border-white/10 rounded-md px-2 py-1 text-white"
                >
                  {Object.keys(STAGE_CFG).filter(s => s !== "").map(s => (
                    <option key={s} value={s}>{STAGE_CFG[s].label}</option>
                  ))}
                </select>
              ) : (
                <button onClick={() => setEditStage(true)} title="Click to change stage">
                  <StageBadge stage={stage} />
                </button>
              )}
            </div>
          </div>

          {/* Key history */}
          <div className="mt-3">
            <p className="text-[9px] uppercase tracking-widest text-[#475569] mb-2">Key History</p>
            <KeyHistory keys={contact.keys} />
          </div>

          {/* Notes */}
          {contact.notes && (
            <p className="mt-3 text-xs text-[#94A3B8] italic">&quot;{contact.notes}&quot;</p>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 mt-3 pt-3 border-t border-white/6">
            <button className="text-xs text-[#94A3B8] hover:text-white flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-colors">
              <Mail size={12} /> Send email
            </button>
            <button
              onClick={() => setExpanded(e => !e)}
              className="text-xs text-[#94A3B8] hover:text-white flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-colors ml-auto">
              {expanded ? "▲ Less" : "▼ Details"}
            </button>
          </div>

          {/* Expanded details */}
          {expanded && (
            <div className="mt-3 pt-3 border-t border-white/6 grid grid-cols-2 gap-3 text-xs">
              <div>
                <p className="text-[9px] uppercase tracking-widest text-[#475569] mb-1">Follow-up</p>
                <p className={overdue ? "text-amber-400" : "text-[#94A3B8]"}>
                  {fmtDateOrDash(contact.follow_up_date)}
                </p>
              </div>
              <div>
                <p className="text-[9px] uppercase tracking-widest text-[#475569] mb-1">Last Active</p>
                <p className="text-[#94A3B8]">{fmtDateOrDash(contact.latest_activity)}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function ContactsPage() {
  const { secret }  = useAdmin()
  const [contacts, setContacts] = useState<Contact[]>([])
  const [loading, setLoading]   = useState(true)
  const [search, setSearch]     = useState("")
  const [filter, setFilter]     = useState<"all" | "follow-up">("all")

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setContacts(await adminApi.getContacts(secret))
    } finally {
      setLoading(false)
    }
  }, [secret])

  useEffect(() => { load() }, [load])

  const today   = new Date().toISOString().slice(0, 10)
  const visible = contacts.filter(c => {
    const matchSearch = !search || [c.email, c.name, c.company].some(
      f => f?.toLowerCase().includes(search.toLowerCase())
    )
    const matchFilter = filter === "all" || (c.follow_up_date && c.follow_up_date <= today)
    return matchSearch && matchFilter
  })
  const overdueCount = contacts.filter(c => c.follow_up_date && c.follow_up_date <= today).length

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="bg-[#0D1B2A] border-b border-white/8 px-6 py-4 flex items-center gap-4">
        <div className="flex items-center gap-2 flex-1">
          <Users size={16} className="text-[#00DC82]" />
          <h1 className="text-sm font-bold text-white">Contacts</h1>
          <span className="text-xs text-[#64748B] ml-2">{contacts.length} total</span>
        </div>
        <div className="flex items-center gap-3">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search…"
            className="bg-[#060B14] border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white placeholder-[#475569] focus:outline-none focus:border-[#7C3AED]/60 w-48"
          />
          <div className="flex gap-1">
            {(["all", "follow-up"] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`text-xs px-3 py-1.5 rounded-md transition-colors ${filter === f ? "bg-white/8 text-white" : "text-[#94A3B8] hover:text-white hover:bg-white/5"}`}>
                {f === "all" ? "All" : `Follow-up due${overdueCount > 0 ? ` (${overdueCount})` : ""}`}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-[#94A3B8] text-sm">Loading…</div>
        ) : visible.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-[#94A3B8]">
            <Users size={32} className="mb-3 opacity-30" />
            <p className="text-sm">No contacts yet — issue a key to get started</p>
          </div>
        ) : (
          <div className="space-y-3 max-w-3xl">
            {visible.map(c => (
              <ContactCard key={c.email} contact={c} secret={secret} onUpdated={load} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
