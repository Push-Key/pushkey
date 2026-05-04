"use client"
import { useEffect, useMemo, useState, useCallback } from "react"
import {
  Users, Mail, Plus, X, Send, Copy, Check, Edit3, AlertCircle, Clock,
  ChevronLeft, ChevronRight,
} from "lucide-react"
import {
  adminApi, maskKey, fmtDateOrDash, isOverdue, isExpiringSoon,
  type Contact, type ContactKey, type IssueKeyRequest, type License,
} from "@/lib/admin-api"
import { useAdmin } from "../_context"

// ── Stage config ─────────────────────────────────────────────────
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

const SOURCES = ["Twitter", "ProductHunt", "Referral", "Direct", "Conference", "Other"] as const

// ── Helpers ──────────────────────────────────────────────────────
function inputCls(extra = "") {
  return `mt-1 w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/40 outline-none focus:border-[#00DC82]/50 transition-colors ${extra}`
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-xs text-[#94A3B8] uppercase tracking-wider">
        {label}{required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  )
}

// ── Stage badge ──────────────────────────────────────────────────
function StageBadge({ stage }: { stage: string }) {
  const c = STAGE_CFG[stage] ?? STAGE_CFG[""]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${c.bg} ${c.text} ${c.border}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
      {c.label}
    </span>
  )
}

// ── Stat card ────────────────────────────────────────────────────
function StatCard({ label, value, sub, accent }: { label: string; value: number; sub: string; accent: string }) {
  return (
    <div className="relative bg-[#0D1B2A] border border-white/8 rounded-xl p-4 overflow-hidden flex-1 min-w-0">
      <div className={`absolute left-0 top-0 bottom-0 w-1 rounded-l-xl ${accent}`} />
      <p className="text-[10px] tracking-widest uppercase text-[#94A3B8] mb-1.5">{label}</p>
      <p className="text-2xl font-bold text-white">{value.toLocaleString()}</p>
      <p className="text-[11px] text-[#94A3B8] mt-0.5">{sub}</p>
    </div>
  )
}

// ── Issue Key modal ──────────────────────────────────────────────
function IssueKeyModal({ initialEmail, onClose, onIssued }: {
  initialEmail?: string
  onClose: () => void
  onIssued: () => void
}) {
  const { secret } = useAdmin()
  const [form, setForm] = useState<IssueKeyRequest>({
    email: initialEmail ?? "",
    tier: "pro",
    name: "",
    company: "",
    source: "Direct",
    trial_days: null,
    follow_up_date: "",
    notes: "",
    send_email: true,
  })
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState("")
  const [result, setResult] = useState<{ key: string; tier: string; email: string; emailSent: boolean; emailReason?: string } | null>(null)
  const [copied, setCopied] = useState(false)

  function set<K extends keyof IssueKeyRequest>(k: K, v: IssueKeyRequest[K]) {
    setForm(f => ({ ...f, [k]: v }))
  }

  async function submit() {
    setErr("")
    setLoading(true)
    try {
      const resp = await adminApi.issueKey(secret, form)
      setResult({
        key: resp.key,
        tier: resp.tier,
        email: resp.email,
        emailSent: resp.email_result?.sent ?? false,
        emailReason: resp.email_result?.reason,
      })
      onIssued()
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-[#0D1B2A] border border-white/10 rounded-2xl p-6 w-full max-w-lg shadow-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-5">
          <p className="font-semibold text-white">Issue License Key</p>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-white transition-colors"><X size={18} /></button>
        </div>

        {result ? (
          <div className="space-y-4">
            <p className="text-sm text-[#94A3B8]">
              Issued <span className="text-white font-medium">{result.tier}</span> key for <span className="text-white">{result.email}</span>
            </p>
            <div className="bg-[#060B14] border border-[#00DC82]/30 rounded-lg px-4 py-3 flex items-center gap-3">
              <p className="font-mono text-sm text-[#00DC82] break-all flex-1">{result.key}</p>
              <button onClick={copyKey} className="shrink-0 text-[#94A3B8] hover:text-[#00DC82] transition-colors">
                {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
              </button>
            </div>
            {form.send_email && (
              <div className={`text-xs px-3 py-2 rounded-lg border ${result.emailSent ? "bg-emerald-900/20 border-emerald-800/40 text-emerald-300" : "bg-amber-900/20 border-amber-800/40 text-amber-300"}`}>
                {result.emailSent ? "✓ Invite email sent" : `! Email not sent — ${result.emailReason ?? "unknown reason"}`}
              </div>
            )}
            <button onClick={onClose} className="w-full bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2.5 rounded-lg hover:bg-[#00DC82]/90 transition-colors">
              Done
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Email" required>
                <input value={form.email} onChange={e => set("email", e.target.value)} placeholder="user@example.com" type="email" className={inputCls()} />
              </Field>
              <Field label="Tier" required>
                <select value={form.tier} onChange={e => set("tier", e.target.value as License["tier"])} className={inputCls()}>
                  <option value="free">🔲 Free</option>
                  <option value="starter">🚀 Starter</option>
                  <option value="pro">⚡ Pro</option>
                  <option value="team">👥 Team</option>
                  <option value="enterprise">🏛️ Enterprise</option>
                </select>
              </Field>
              <Field label="Name">
                <input value={form.name} onChange={e => set("name", e.target.value)} placeholder="John Doe" className={inputCls()} />
              </Field>
              <Field label="Company">
                <input value={form.company} onChange={e => set("company", e.target.value)} placeholder="Acme Inc." className={inputCls()} />
              </Field>
              <Field label="Source">
                <select value={form.source} onChange={e => set("source", e.target.value)} className={inputCls()}>
                  {SOURCES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </Field>
              <Field label="Trial">
                <select
                  value={form.trial_days === null || form.trial_days === undefined ? "" : String(form.trial_days)}
                  onChange={e => set("trial_days", e.target.value === "" ? null : Number(e.target.value) as 7 | 14 | 30)}
                  className={inputCls()}
                >
                  <option value="">No trial</option>
                  <option value="7">7 days</option>
                  <option value="14">14 days</option>
                  <option value="30">30 days</option>
                </select>
              </Field>
              <Field label="Follow-up Date">
                <input type="date" value={form.follow_up_date} onChange={e => set("follow_up_date", e.target.value)} className={inputCls()} />
              </Field>
              <div>
                <label className="text-xs text-[#94A3B8] uppercase tracking-wider">Send invite email</label>
                <label className="flex items-center gap-2 mt-2 cursor-pointer">
                  <input type="checkbox" checked={form.send_email} onChange={e => set("send_email", e.target.checked)} className="w-4 h-4 accent-[#00DC82]" />
                  <span className="text-sm text-white">Email license to user</span>
                </label>
              </div>
            </div>
            <Field label="Notes">
              <textarea value={form.notes} onChange={e => set("notes", e.target.value)} rows={2} className={inputCls("resize-none")} />
            </Field>

            {err && <p className="text-xs text-red-400 bg-red-900/20 border border-red-800/40 px-3 py-2 rounded-lg">{err}</p>}

            <div className="flex gap-3 pt-1">
              <button onClick={onClose} className="flex-1 border border-white/10 text-[#94A3B8] text-sm py-2.5 rounded-lg hover:border-white/20 hover:text-white transition-colors">Cancel</button>
              <button
                onClick={submit}
                disabled={loading || !form.email}
                className="flex-1 bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2.5 rounded-lg hover:bg-[#00DC82]/90 disabled:opacity-40 transition-colors"
              >
                {loading ? "Issuing…" : "Issue Key"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Edit Contact modal ───────────────────────────────────────────
function EditContactModal({ contact, onClose, onSaved }: {
  contact: Contact
  onClose: () => void
  onSaved: () => void
}) {
  const { secret } = useAdmin()
  const [form, setForm] = useState({
    name:           contact.name,
    company:        contact.company,
    source:         contact.source || "Direct",
    follow_up_date: contact.follow_up_date,
    stage:          contact.stage || "active",
    notes:          contact.notes,
  })
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState("")

  async function save() {
    setLoading(true); setErr("")
    try {
      await adminApi.updateContact(secret, contact.email, form)
      onSaved()
      onClose()
    } catch (e) {
      setErr(String(e))
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-[#0D1B2A] border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <div>
            <p className="font-semibold text-white">Edit Contact</p>
            <p className="text-xs text-[#94A3B8]">{contact.email}</p>
          </div>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-white"><X size={18} /></button>
        </div>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name">
              <input value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} className={inputCls()} />
            </Field>
            <Field label="Company">
              <input value={form.company} onChange={e => setForm(f => ({...f, company: e.target.value}))} className={inputCls()} />
            </Field>
            <Field label="Source">
              <select value={form.source} onChange={e => setForm(f => ({...f, source: e.target.value}))} className={inputCls()}>
                {SOURCES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>
            <Field label="Stage">
              <select value={form.stage} onChange={e => setForm(f => ({...f, stage: e.target.value}))} className={inputCls()}>
                {Object.keys(STAGE_CFG).filter(s => s !== "").map(s => (
                  <option key={s} value={s}>{STAGE_CFG[s].label}</option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Follow-up Date">
            <input type="date" value={form.follow_up_date} onChange={e => setForm(f => ({...f, follow_up_date: e.target.value}))} className={inputCls()} />
          </Field>
          <Field label="Notes">
            <textarea value={form.notes} onChange={e => setForm(f => ({...f, notes: e.target.value}))} rows={3} className={inputCls("resize-none")} />
          </Field>
          {err && <p className="text-xs text-red-400">{err}</p>}
          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="flex-1 border border-white/10 text-[#94A3B8] text-sm py-2.5 rounded-lg hover:border-white/20 hover:text-white transition-colors">Cancel</button>
            <button onClick={save} disabled={loading} className="flex-1 bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2.5 rounded-lg hover:bg-[#00DC82]/90 disabled:opacity-40 transition-colors">
              {loading ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Key row (inside expanded card) ───────────────────────────────
function KeyRow({ k, onAction }: { k: ContactKey; onAction: () => void }) {
  const { secret } = useAdmin()
  const [busy, setBusy] = useState<string | null>(null)
  const expSoon  = isExpiringSoon(k.expires_at)
  const expPast  = k.expires_at && k.expires_at < new Date().toISOString()

  async function run(tag: string, fn: () => Promise<unknown>) {
    setBusy(tag)
    try { await fn(); onAction() } finally { setBusy(null) }
  }

  return (
    <div className="bg-[#060B14] rounded-md px-3 py-2 border border-white/6 flex items-center gap-3 text-xs">
      <span>{TIER_ICONS[k.tier] ?? "🔑"}</span>
      <span className="font-mono text-sky-400 flex-1 min-w-0 truncate">{maskKey(k.key)}</span>
      <span className={`shrink-0 ${k.status === "active" ? "text-emerald-400" : k.status === "revoked" ? "text-red-400" : "text-amber-400"}`}>
        {k.status}
      </span>
      {k.expires_at && (
        <span className={`shrink-0 ${expPast ? "text-red-400" : expSoon ? "text-amber-400" : "text-[#94A3B8]"}`}>
          {expSoon && !expPast && <Clock size={10} className="inline mr-1 mb-0.5" />}
          exp {fmtDateOrDash(k.expires_at)}
        </span>
      )}
      <div className="flex items-center gap-1 shrink-0">
        <button
          onClick={() => run("invite", () => adminApi.sendInvite(secret, k.key))}
          disabled={busy === "invite"}
          title="Resend invite email"
          className="border border-sky-700/60 bg-sky-900/30 text-sky-300 hover:bg-sky-900/50 disabled:opacity-40 px-2 py-0.5 rounded text-[10px] flex items-center gap-1 transition-colors"
        >
          <Send size={9} /> {busy === "invite" ? "…" : "Invite"}
        </button>
        {k.status === "expired" && (
          <button
            onClick={() => run("renew", () => adminApi.renew(secret, k.key))}
            disabled={busy === "renew"}
            className="border border-emerald-700/60 bg-emerald-900/30 text-emerald-300 hover:bg-emerald-900/50 disabled:opacity-40 px-2 py-0.5 rounded text-[10px] transition-colors"
          >
            {busy === "renew" ? "…" : "Renew"}
          </button>
        )}
        {k.status !== "revoked" && (
          <button
            onClick={() => run("revoke", () => adminApi.revoke(secret, k.key))}
            disabled={busy === "revoke"}
            className="border border-red-700/60 bg-red-900/30 text-red-300 hover:bg-red-900/50 disabled:opacity-40 px-2 py-0.5 rounded text-[10px] transition-colors"
          >
            {busy === "revoke" ? "…" : "Revoke"}
          </button>
        )}
      </div>
    </div>
  )
}

// ── Contact card ─────────────────────────────────────────────────
function ContactCard({ contact, onEdit, onIssue, onRefresh }: {
  contact: Contact
  onEdit: (c: Contact) => void
  onIssue: (email: string) => void
  onRefresh: () => void
}) {
  const { secret } = useAdmin()
  const [editStage, setEditStage] = useState(false)
  const [stage, setStage]         = useState(contact.stage)
  const [expanded, setExpanded]   = useState(false)
  const overdue   = isOverdue(contact.follow_up_date)
  const initial   = (contact.name || contact.email).charAt(0).toUpperCase()
  const expSoon   = contact.keys.some(k => isExpiringSoon(k.expires_at))
  const activeKey = contact.keys.filter(k => k.status === "active").length

  const borderColor = overdue ? "border-amber-600/50"
    : expSoon ? "border-sky-700/40"
    : stage === "converted" ? "border-emerald-700/40"
    : "border-white/8"
  const leftBar = overdue ? "bg-amber-500"
    : expSoon ? "bg-sky-500"
    : stage === "converted" ? "bg-emerald-500"
    : "bg-[#1E293B]"

  async function saveStage(s: string) {
    await adminApi.updateContact(secret, contact.email, { stage: s })
    setStage(s)
    setEditStage(false)
    onRefresh()
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
            <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
              {overdue && contact.follow_up_date && (
                <span className="bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[10px] font-semibold px-2 py-1 rounded-full flex items-center gap-1">
                  <AlertCircle size={10} /> Follow-up {fmtDateOrDash(contact.follow_up_date)}
                </span>
              )}
              {expSoon && !overdue && (
                <span className="bg-sky-500/20 border border-sky-500/40 text-sky-300 text-[10px] font-semibold px-2 py-1 rounded-full flex items-center gap-1">
                  <Clock size={10} /> Expiring soon
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
            <p className="text-[9px] uppercase tracking-widest text-[#475569] mb-2 flex items-center justify-between">
              <span>Key History · {activeKey}/{contact.keys.length} active</span>
            </p>
            {contact.keys.length === 0 ? (
              <p className="text-xs text-[#94A3B8]">No keys issued</p>
            ) : (
              <div className="space-y-1.5">
                {contact.keys.map(k => (
                  <KeyRow key={k.key} k={k} onAction={onRefresh} />
                ))}
              </div>
            )}
          </div>

          {/* Notes */}
          {contact.notes && (
            <p className="mt-3 text-xs text-[#94A3B8] italic">&quot;{contact.notes}&quot;</p>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 mt-3 pt-3 border-t border-white/6">
            <a
              href={`mailto:${contact.email}`}
              className="text-xs text-[#94A3B8] hover:text-white flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-colors"
            >
              <Mail size={12} /> Email
            </a>
            <button
              onClick={() => onEdit(contact)}
              className="text-xs text-[#94A3B8] hover:text-white flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-colors"
            >
              <Edit3 size={12} /> Edit
            </button>
            <button
              onClick={() => onIssue(contact.email)}
              className="text-xs text-emerald-300 hover:text-emerald-200 flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-emerald-900/20 border border-emerald-800/40 hover:bg-emerald-900/40 transition-colors"
            >
              <Plus size={12} /> Issue Key
            </button>
            <button
              onClick={() => setExpanded(e => !e)}
              className="text-xs text-[#94A3B8] hover:text-white flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-colors ml-auto"
            >
              {expanded ? "▲ Less" : "▼ More"}
            </button>
          </div>

          {/* Expanded details */}
          {expanded && (
            <div className="mt-3 pt-3 border-t border-white/6 grid grid-cols-3 gap-3 text-xs">
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
              <div>
                <p className="text-[9px] uppercase tracking-widest text-[#475569] mb-1">Source</p>
                <p className="text-[#94A3B8]">{contact.source || "—"}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Filter tabs ──────────────────────────────────────────────────
const FILTERS = ["All", "Trial", "Active", "Converted", "Churned", "Cold", "Overdue", "Expiring"] as const
const PAGE_SIZE = 10

export default function ContactsPage() {
  const { secret } = useAdmin()
  const [contacts, setContacts] = useState<Contact[]>([])
  const [loading, setLoading]   = useState(true)
  const [search, setSearch]     = useState("")
  const [filter, setFilter]     = useState<typeof FILTERS[number]>("All")
  const [page, setPage]         = useState(1)
  const [issuing, setIssuing]   = useState<{ open: boolean; email?: string }>({ open: false })
  const [editing, setEditing]   = useState<Contact | null>(null)

  const load = useCallback(async () => {
    if (!secret) return
    setLoading(true)
    try {
      setContacts(await adminApi.getContacts(secret))
    } finally {
      setLoading(false)
    }
  }, [secret])

  useEffect(() => { load() }, [load])

  const filtered = useMemo(() => {
    let list = contacts
    if (filter === "Overdue") {
      list = list.filter(c => isOverdue(c.follow_up_date))
    } else if (filter === "Expiring") {
      list = list.filter(c => c.keys.some(k => isExpiringSoon(k.expires_at)))
    } else if (filter !== "All") {
      list = list.filter(c => (c.stage || "").toLowerCase() === filter.toLowerCase())
    }
    if (search) {
      const q = search.toLowerCase()
      list = list.filter(c =>
        c.email.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        c.company.toLowerCase().includes(q) ||
        (c.source ?? "").toLowerCase().includes(q),
      )
    }
    return list
  }, [contacts, filter, search])

  const stats = useMemo(() => ({
    total:    contacts.length,
    trial:    contacts.filter(c => c.stage === "trial").length,
    overdue:  contacts.filter(c => isOverdue(c.follow_up_date)).length,
    expiring: contacts.filter(c => c.keys.some(k => isExpiringSoon(k.expires_at))).length,
  }), [contacts])

  return (
    <div className="p-8">
      {issuing.open && (
        <IssueKeyModal
          initialEmail={issuing.email}
          onClose={() => setIssuing({ open: false })}
          onIssued={load}
        />
      )}
      {editing && (
        <EditContactModal
          contact={editing}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Users size={18} className="text-[#00DC82]" />
            Contacts <span className="text-[#94A3B8] font-normal text-base">{filtered.length} shown</span>
          </h1>
          <p className="text-sm text-[#94A3B8] mt-1">CRM view — track customers, trials, and follow-ups</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <input
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1) }}
              placeholder="Search email, name, company…"
              className="bg-[#0D1B2A] border border-white/8 rounded-lg px-3 py-2 text-sm text-white placeholder-[#475569] outline-none focus:border-white/20 w-64 transition-colors"
            />
          </div>
          <button
            onClick={() => setIssuing({ open: true })}
            className="flex items-center gap-2 bg-[#00DC82] text-[#060B14] font-semibold text-sm px-4 py-2 rounded-lg hover:bg-[#00DC82]/90 transition-colors"
          >
            <Plus size={14} /> Issue Key
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="flex gap-4 mb-6">
        <StatCard label="Total Contacts"     value={stats.total}    sub="All customers"            accent="bg-emerald-500" />
        <StatCard label="In Trial"            value={stats.trial}    sub="Trial period"             accent="bg-violet-500" />
        <StatCard label="Overdue Follow-ups" value={stats.overdue}  sub="Needs attention today"   accent="bg-amber-500" />
        <StatCard label="Expiring Soon"       value={stats.expiring} sub="Within 7 days"           accent="bg-red-500" />
      </div>

      {/* Filter pills */}
      <div className="flex items-center gap-1 mb-5 flex-wrap">
        {FILTERS.map(f => {
          const count = f === "All" ? contacts.length
            : f === "Overdue" ? stats.overdue
            : f === "Expiring" ? stats.expiring
            : contacts.filter(c => (c.stage || "").toLowerCase() === f.toLowerCase()).length
          return (
            <button
              key={f}
              onClick={() => { setFilter(f); setPage(1) }}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                filter === f ? "bg-white/10 text-white" : "text-[#94A3B8] hover:text-white hover:bg-white/5"
              }`}
            >
              {f} {count > 0 && <span className="text-[#475569]">· {count}</span>}
            </button>
          )
        })}
      </div>

      {/* Pagination math */}
      {(() => {
        const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
        const safePage   = Math.min(page, totalPages)
        const pageData   = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)
        const pageNums = (() => {
          if (totalPages <= 5) return Array.from({ length: totalPages }, (_, i) => i + 1)
          const start = Math.max(1, Math.min(safePage - 2, totalPages - 4))
          return Array.from({ length: 5 }, (_, i) => start + i)
        })()

        if (loading) {
          return <div className="flex items-center justify-center h-40 text-[#94A3B8] text-sm">Loading…</div>
        }
        if (filtered.length === 0) {
          return (
            <div className="flex flex-col items-center justify-center h-60 text-[#94A3B8] bg-[#0D1B2A] border border-white/8 rounded-xl">
              <Users size={32} className="mb-3 opacity-30" />
              <p className="text-sm">No contacts found</p>
              <p className="text-xs text-[#475569] mt-1">Issue a license key with an email to create your first contact</p>
            </div>
          )
        }
        return (
          <>
            <div className="space-y-3">
              {pageData.map(c => (
                <ContactCard
                  key={c.email}
                  contact={c}
                  onEdit={setEditing}
                  onIssue={(email) => setIssuing({ open: true, email })}
                  onRefresh={load}
                />
              ))}
            </div>

            {/* Pagination footer */}
            <div className="mt-5 flex items-center justify-between bg-[#0D1B2A] border border-white/8 rounded-xl px-5 py-3">
              <p className="text-xs text-[#94A3B8]">
                Showing {(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)} of {filtered.length}
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={safePage === 1}
                  className="w-7 h-7 flex items-center justify-center rounded text-xs text-[#94A3B8] hover:text-white hover:bg-white/8 disabled:opacity-30 transition-colors"
                ><ChevronLeft size={14} /></button>
                {pageNums[0] > 1 && <span className="text-[#94A3B8] text-xs px-1">…</span>}
                {pageNums.map(n => (
                  <button
                    key={n}
                    onClick={() => setPage(n)}
                    className={`w-7 h-7 flex items-center justify-center rounded text-xs transition-colors ${safePage === n ? "bg-white/15 text-white" : "text-[#94A3B8] hover:text-white hover:bg-white/8"}`}
                  >{n}</button>
                ))}
                {pageNums[pageNums.length - 1] < totalPages && <span className="text-[#94A3B8] text-xs px-1">…</span>}
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={safePage === totalPages}
                  className="w-7 h-7 flex items-center justify-center rounded text-xs text-[#94A3B8] hover:text-white hover:bg-white/8 disabled:opacity-30 transition-colors"
                ><ChevronRight size={14} /></button>
              </div>
            </div>
          </>
        )
      })()}
    </div>
  )
}
