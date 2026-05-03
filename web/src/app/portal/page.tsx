"use client"
import { useState } from "react"
import Image from "next/image"
import { KeyRound, Calendar, Activity, Monitor, Mail, Send, AlertCircle, CheckCircle, Clock, X } from "lucide-react"

const API = process.env.NEXT_PUBLIC_ADMIN_API_URL ?? "http://localhost:8000"

interface PortalLicense {
  key: string
  tier: "free" | "starter" | "pro" | "team" | "enterprise"
  status: "active" | "expired" | "revoked"
  email: string
  name: string
  activated: string
  expires_at: string | null
  last_heartbeat: string | null
  platform: string
  stage: string
}

const TIER_CFG: Record<string, { label: string; icon: string; color: string; bg: string; features: string[] }> = {
  free:       { label: "Free",       icon: "🔲", color: "text-sky-300",     bg: "bg-sky-900/30",    features: ["15 keys", "1 project", "1 device"] },
  starter:    { label: "Starter",    icon: "🚀", color: "text-violet-300",  bg: "bg-violet-900/30", features: ["50 keys", "3 projects", "Cloud sync", "Git scan"] },
  pro:        { label: "Pro",        icon: "⚡", color: "text-purple-200",  bg: "bg-purple-900/40", features: ["Unlimited keys", "Unlimited projects", "3 devices", "Cloud sync", "CI sync"] },
  team:       { label: "Team",       icon: "👥", color: "text-teal-300",    bg: "bg-teal-900/30",   features: ["Unlimited keys", "Unlimited projects", "5 devices", "Team RBAC"] },
  enterprise: { label: "Enterprise", icon: "🏛️", color: "text-amber-300",   bg: "bg-amber-900/30",  features: ["Unlimited everything", "Hardware MFA", "SSO", "Dynamic secrets"] },
}

const STATUS_CFG = {
  active:  { dot: "bg-emerald-400", text: "text-emerald-400", icon: <CheckCircle size={14} />, label: "Active" },
  expired: { dot: "bg-amber-400",   text: "text-amber-400",   icon: <Clock size={14} />,       label: "Expired" },
  revoked: { dot: "bg-red-400",     text: "text-red-400",     icon: <X size={14} />,           label: "Revoked" },
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—"
  return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })
}

function timeAgo(iso: string | null): string {
  if (!iso) return "Never"
  const diff = Date.now() - new Date(iso).getTime()
  const hrs = Math.floor(diff / 3600000)
  if (hrs < 1) return "Just now"
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null
  return Math.ceil((new Date(iso).getTime() - Date.now()) / (24 * 3600 * 1000))
}

export default function PortalPage() {
  const [keyInput, setKeyInput] = useState("")
  const [license, setLicense] = useState<PortalLicense | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [renewMsg, setRenewMsg] = useState("")
  const [renewing, setRenewing] = useState(false)
  const [renewSent, setRenewSent] = useState(false)

  async function lookup(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    setLoading(true)
    setLicense(null)
    try {
      const r = await fetch(`${API}/api/v1/portal/lookup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ license_key: keyInput.trim() }),
      })
      if (r.status === 404) {
        setError("License key not found. Double-check and try again.")
      } else if (!r.ok) {
        setError("Could not look up license. Please try again later.")
      } else {
        setLicense(await r.json())
      }
    } catch {
      setError("Network error. Check your connection and try again.")
    } finally {
      setLoading(false)
    }
  }

  async function requestRenewal() {
    if (!license) return
    setRenewing(true)
    try {
      await fetch(`${API}/api/v1/portal/request-renewal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ license_key: license.key, message: renewMsg }),
      })
      setRenewSent(true)
      setRenewMsg("")
    } finally {
      setRenewing(false)
    }
  }

  function logout() {
    setLicense(null)
    setKeyInput("")
    setRenewSent(false)
    setRenewMsg("")
    setError("")
  }

  // ── Lookup view ───────────────────────────────────────────────
  if (!license) {
    return (
      <div className="min-h-screen bg-[#060B14] flex items-center justify-center p-4">
        <div className="w-full max-w-md">
          <div className="flex items-center justify-center gap-3 mb-8">
            <Image src="/pushkey-logo.png" alt="Pushkey" width={56} height={56} />
            <div>
              <p className="text-base font-bold tracking-wide text-white leading-none">PUSHKEY</p>
              <p className="text-[9px] text-[#94A3B8] tracking-widest uppercase">Customer Portal</p>
            </div>
          </div>

          <form onSubmit={lookup} className="bg-[#0D1B2A] border border-white/8 rounded-xl p-6 space-y-4">
            <div>
              <p className="text-sm font-semibold text-white mb-1">View Your License</p>
              <p className="text-xs text-[#94A3B8] mb-4">Enter the license key you received via email to see status, expiry, and request renewal.</p>
              <div className="relative">
                <KeyRound size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
                <input
                  value={keyInput}
                  onChange={e => setKeyInput(e.target.value.toUpperCase())}
                  placeholder="PRO-XXXX-XXXXXXX-XXXX"
                  className="w-full bg-[#112233] border border-white/8 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white font-mono placeholder:text-[#94A3B8]/40 outline-none focus:border-[#00DC82]/50 transition-colors"
                  autoFocus
                />
              </div>
            </div>

            {error && (
              <div className="text-xs text-red-300 bg-red-900/20 border border-red-800/40 px-3 py-2 rounded-lg flex items-start gap-2">
                <AlertCircle size={14} className="shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !keyInput.trim()}
              className="w-full bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2.5 rounded-lg hover:bg-[#00DC82]/90 disabled:opacity-40 transition-colors"
            >
              {loading ? "Looking up…" : "View License"}
            </button>

            <p className="text-[10px] text-center text-[#94A3B8]/60">
              Lost your key? <a href="mailto:support@pushkey.app" className="text-sky-400 hover:text-sky-300">Contact support</a>
            </p>
          </form>
        </div>
      </div>
    )
  }

  // ── License view ──────────────────────────────────────────────
  const cfg     = TIER_CFG[license.tier] ?? TIER_CFG.free
  const statCfg = STATUS_CFG[license.status]
  const dleft   = daysUntil(license.expires_at)
  const expSoon = dleft !== null && dleft > 0 && dleft <= 30
  const expired = license.status === "expired" || (dleft !== null && dleft <= 0)

  return (
    <div className="min-h-screen bg-[#060B14] py-10 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <Image src="/pushkey-logo.png" alt="Pushkey" width={48} height={48} />
            <div>
              <p className="text-sm font-bold tracking-wide text-white leading-none">PUSHKEY</p>
              <p className="text-[9px] text-[#94A3B8] tracking-widest uppercase">Customer Portal</p>
            </div>
          </div>
          <button onClick={logout} className="text-xs text-[#94A3B8] hover:text-white transition-colors">
            Sign out
          </button>
        </div>

        {/* Hero card */}
        <div className={`${cfg.bg} border border-white/10 rounded-2xl p-6 mb-5`}>
          <div className="flex items-start justify-between mb-4">
            <div>
              <p className="text-xs text-[#94A3B8] uppercase tracking-widest mb-1">Your Plan</p>
              <p className={`text-3xl font-bold ${cfg.color} flex items-center gap-2`}>
                <span>{cfg.icon}</span>{cfg.label}
              </p>
              {license.name && <p className="text-sm text-white mt-2">{license.name}</p>}
              {license.email && <p className="text-xs text-[#94A3B8]">{license.email}</p>}
            </div>
            <span className={`flex items-center gap-1.5 text-sm font-medium ${statCfg.text} bg-black/30 px-3 py-1.5 rounded-full`}>
              {statCfg.icon} {statCfg.label}
            </span>
          </div>

          {/* License key */}
          <div className="bg-black/30 border border-white/10 rounded-lg px-4 py-3 mb-4">
            <p className="text-[10px] uppercase tracking-widest text-[#94A3B8] mb-1">License Key</p>
            <p className="font-mono text-sm text-sky-400 break-all">{license.key}</p>
          </div>

          {/* Features */}
          <div>
            <p className="text-[10px] uppercase tracking-widest text-[#94A3B8] mb-2">What&apos;s Included</p>
            <div className="flex flex-wrap gap-1.5">
              {cfg.features.map(f => (
                <span key={f} className="text-xs bg-black/30 text-white/80 px-2.5 py-1 rounded-full border border-white/10">{f}</span>
              ))}
            </div>
          </div>
        </div>

        {/* Expiry banner */}
        {expired && (
          <div className="bg-red-900/30 border border-red-800/50 rounded-xl p-4 mb-5">
            <p className="text-sm font-semibold text-red-300 flex items-center gap-2">
              <AlertCircle size={16} /> Your license has expired
            </p>
            <p className="text-xs text-red-300/80 mt-1">Request a renewal below to restore your premium features.</p>
          </div>
        )}
        {expSoon && !expired && (
          <div className="bg-amber-900/30 border border-amber-800/50 rounded-xl p-4 mb-5">
            <p className="text-sm font-semibold text-amber-300 flex items-center gap-2">
              <Clock size={16} /> Expires in {dleft} day{dleft !== 1 ? "s" : ""}
            </p>
            <p className="text-xs text-amber-300/80 mt-1">Request a renewal below to extend your license.</p>
          </div>
        )}

        {/* Details grid */}
        <div className="grid grid-cols-2 gap-3 mb-5">
          {[
            { icon: <Calendar size={14} />, label: "Activated",   value: fmtDate(license.activated) },
            { icon: <Calendar size={14} />, label: "Expires",     value: license.expires_at ? fmtDate(license.expires_at) : "Never" },
            { icon: <Activity size={14} />, label: "Last seen",   value: timeAgo(license.last_heartbeat) },
            { icon: <Monitor size={14} />,  label: "Platform",    value: license.platform || "—" },
          ].map(d => (
            <div key={d.label} className="bg-[#0D1B2A] border border-white/8 rounded-lg p-3 flex items-center gap-3">
              <div className="w-8 h-8 rounded-md bg-white/5 flex items-center justify-center text-[#94A3B8]">{d.icon}</div>
              <div>
                <p className="text-[10px] uppercase tracking-widest text-[#94A3B8]">{d.label}</p>
                <p className="text-sm text-white">{d.value}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Renewal */}
        <div className="bg-[#0D1B2A] border border-white/8 rounded-xl p-5">
          <p className="text-sm font-semibold text-white mb-1">Need help or want to renew?</p>
          <p className="text-xs text-[#94A3B8] mb-4">Send a message and our team will get back to you within 1 business day.</p>

          {renewSent ? (
            <div className="bg-emerald-900/20 border border-emerald-800/40 rounded-lg p-3 text-sm text-emerald-300 flex items-center gap-2">
              <CheckCircle size={16} /> Request sent! We&apos;ll be in touch at <strong>{license.email}</strong>.
            </div>
          ) : (
            <>
              <textarea
                value={renewMsg}
                onChange={e => setRenewMsg(e.target.value)}
                rows={3}
                placeholder="Tell us what you need (renewal, upgrade, billing question, technical issue)…"
                className="w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/40 outline-none focus:border-[#00DC82]/50 transition-colors resize-none mb-3"
              />
              <div className="flex items-center gap-3">
                <a
                  href={`mailto:support@pushkey.app?subject=Re:%20${license.key}`}
                  className="flex items-center gap-2 border border-white/10 text-[#94A3B8] hover:text-white hover:border-white/20 text-sm px-4 py-2 rounded-lg transition-colors"
                >
                  <Mail size={14} /> Email instead
                </a>
                <button
                  onClick={requestRenewal}
                  disabled={renewing}
                  className="flex-1 flex items-center justify-center gap-2 bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2 rounded-lg hover:bg-[#00DC82]/90 disabled:opacity-40 transition-colors"
                >
                  <Send size={14} /> {renewing ? "Sending…" : "Send Request"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
