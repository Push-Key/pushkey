"use client"
import { useState } from "react"
import { MessageSquare, ChevronDown, ChevronUp, CheckCircle, Clock, AlertCircle } from "lucide-react"

interface Ticket {
  id: string
  subject: string
  message: string
  email: string
  priority: "low" | "medium" | "high"
  status: "open" | "pending" | "resolved"
  createdAt: string
}

const FAQS = [
  { q: "How do I rotate a compromised key?", a: "Go to Licenses → find the key → click Expire to immediately invalidate it, then generate a new key for the same tier and email it to the client. The client's app will prompt them to re-enter their license on next launch." },
  { q: "What happens when a license expires?", a: "Expired licenses block access to tier-gated features. The app falls back to Free tier limits. Data is never deleted — the user just sees an upgrade/renew prompt." },
  { q: "Can a client use Pushkey offline?", a: "Yes. There's a 10-day offline grace period. After that, the heartbeat check will gate Pro/Team/Enterprise features until connectivity is restored." },
  { q: "How do I move a client from one tier to another?", a: "Revoke their current key, generate a new key with the target tier, and send it to them. There's no in-place upgrade — keys are immutable once generated." },
  { q: "Where is vault data stored?", a: "Each client's vault is stored locally at ~/.pushkey/vault.enc (AES-256-GCM encrypted). If cloud sync is enabled, an encrypted blob is also stored on your cloud API server — the server never sees plaintext." },
  { q: "How do I set up my own admin password?", a: 'Set the PUSHKEY_ADMIN_SECRET environment variable before starting the cloud API: $env:PUSHKEY_ADMIN_SECRET = "YourPassword123"; uvicorn pushkey_cloud_api:app' },
]

const PRIORITY_CFG = {
  low:    { label: "Low",    color: "text-sky-400",   bg: "bg-sky-900/30 border-sky-800/50" },
  medium: { label: "Medium", color: "text-amber-400", bg: "bg-amber-900/30 border-amber-800/50" },
  high:   { label: "High",   color: "text-red-400",   bg: "bg-red-900/30 border-red-800/50" },
}

const STATUS_CFG = {
  open:     { icon: <AlertCircle size={13} />, color: "text-amber-400", label: "Open" },
  pending:  { icon: <Clock size={13} />,       color: "text-sky-400",   label: "Pending" },
  resolved: { icon: <CheckCircle size={13} />, color: "text-emerald-400", label: "Resolved" },
}

function fmtDate(iso: string) { return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) }

export default function SupportPage() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [openFaq, setOpenFaq] = useState<number | null>(null)
  const [form, setForm] = useState({ subject: "", message: "", email: "", priority: "medium" as Ticket["priority"] })
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  function submitTicket() {
    if (!form.subject || !form.message) return
    setSubmitting(true)
    setTimeout(() => {
      setTickets(t => [{
        id: Date.now().toString(),
        ...form,
        status: "open",
        createdAt: new Date().toISOString(),
      }, ...t])
      setForm({ subject: "", message: "", email: "", priority: "medium" })
      setSubmitted(true)
      setSubmitting(false)
      setTimeout(() => setSubmitted(false), 3000)
    }, 600)
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-xl font-bold text-white">Support</h1>
        <p className="text-sm text-[#94A3B8] mt-1">Submit tickets and browse common answers</p>
      </div>

      <div className="grid grid-cols-5 gap-6">
        {/* Left: ticket form + list */}
        <div className="col-span-3 space-y-6">
          {/* Ticket form */}
          <div className="bg-[#0D1B2A] border border-white/8 rounded-xl p-5">
            <p className="font-semibold text-white mb-4">New Support Ticket</p>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-[#94A3B8] uppercase tracking-wider">Your Email</label>
                  <input
                    value={form.email}
                    onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                    placeholder="you@example.com"
                    className="mt-1 w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/40 outline-none focus:border-[#00DC82]/50 transition-colors"
                  />
                </div>
                <div>
                  <label className="text-xs text-[#94A3B8] uppercase tracking-wider">Priority</label>
                  <select
                    value={form.priority}
                    onChange={e => setForm(f => ({ ...f, priority: e.target.value as Ticket["priority"] }))}
                    className="mt-1 w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white outline-none focus:border-[#00DC82]/50 transition-colors"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="text-xs text-[#94A3B8] uppercase tracking-wider">Subject</label>
                <input
                  value={form.subject}
                  onChange={e => setForm(f => ({ ...f, subject: e.target.value }))}
                  placeholder="Brief description of the issue"
                  className="mt-1 w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/40 outline-none focus:border-[#00DC82]/50 transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-[#94A3B8] uppercase tracking-wider">Message</label>
                <textarea
                  value={form.message}
                  onChange={e => setForm(f => ({ ...f, message: e.target.value }))}
                  rows={4}
                  placeholder="Describe the issue in detail…"
                  className="mt-1 w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/40 outline-none focus:border-[#00DC82]/50 transition-colors resize-none"
                />
              </div>
              <button
                onClick={submitTicket}
                disabled={submitting || !form.subject || !form.message}
                className="w-full bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2.5 rounded-lg hover:bg-[#00DC82]/90 disabled:opacity-40 transition-colors"
              >
                {submitted ? "✓ Ticket submitted" : submitting ? "Submitting…" : "Submit Ticket"}
              </button>
            </div>
          </div>

          {/* Ticket list */}
          {tickets.length > 0 && (
            <div className="bg-[#0D1B2A] border border-white/8 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-white/8">
                <p className="font-semibold text-white">Your Tickets</p>
              </div>
              <div className="divide-y divide-white/5">
                {tickets.map(t => {
                  const p = PRIORITY_CFG[t.priority]
                  const s = STATUS_CFG[t.status]
                  return (
                    <div key={t.id} className="px-5 py-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-white">{t.subject}</p>
                          <p className="text-xs text-[#94A3B8] mt-0.5 line-clamp-2">{t.message}</p>
                          <p className="text-xs text-[#94A3B8]/60 mt-1">{fmtDate(t.createdAt)}</p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className={`text-xs px-2 py-1 rounded-full border ${p.bg} ${p.color}`}>{p.label}</span>
                          <span className={`flex items-center gap-1 text-xs ${s.color}`}>{s.icon} {s.label}</span>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {/* Right: FAQ */}
        <div className="col-span-2">
          <div className="bg-[#0D1B2A] border border-white/8 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-white/8 flex items-center gap-2">
              <MessageSquare size={15} className="text-[#94A3B8]" />
              <p className="font-semibold text-white">FAQ</p>
            </div>
            <div className="divide-y divide-white/5">
              {FAQS.map((faq, i) => (
                <div key={i}>
                  <button
                    onClick={() => setOpenFaq(openFaq === i ? null : i)}
                    className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-white/[0.02] transition-colors"
                  >
                    <span className="text-sm font-medium text-white pr-4">{faq.q}</span>
                    {openFaq === i ? <ChevronUp size={14} className="text-[#94A3B8] shrink-0" /> : <ChevronDown size={14} className="text-[#94A3B8] shrink-0" />}
                  </button>
                  {openFaq === i && (
                    <div className="px-5 pb-4 text-sm text-[#94A3B8] leading-relaxed">
                      {faq.a}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
