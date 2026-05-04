"use client"
import { useEffect, useState } from "react"
import { CheckCircle, AlertCircle, Settings as SettingsIcon, Mail, Shield, Database, Send, Copy, Check, Download } from "lucide-react"
import { adminApi, type AdminSettings } from "@/lib/admin-api"
import { useAdmin } from "../_context"

function StatusRow({ ok, label, value }: { ok: boolean; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-white/5 last:border-b-0">
      <div className="flex items-center gap-2.5">
        {ok ? <CheckCircle size={14} className="text-emerald-400" /> : <AlertCircle size={14} className="text-amber-400" />}
        <span className="text-sm text-white">{label}</span>
      </div>
      <span className="text-sm text-[#94A3B8] font-mono">{value}</span>
    </div>
  )
}

function Section({ icon, title, desc, children }: {
  icon: React.ReactNode; title: string; desc: string; children: React.ReactNode
}) {
  return (
    <div className="bg-[#0D1B2A] border border-white/8 rounded-xl p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-9 h-9 rounded-lg bg-white/5 flex items-center justify-center shrink-0 text-[#94A3B8]">
          {icon}
        </div>
        <div>
          <p className="font-semibold text-white">{title}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">{desc}</p>
        </div>
      </div>
      {children}
    </div>
  )
}

export default function SettingsPage() {
  const { secret } = useAdmin()
  const [settings, setSettings] = useState<AdminSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [testTo, setTestTo] = useState("")
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ sent: boolean; reason?: string } | null>(null)
  const [secretShown, setSecretShown] = useState(false)
  const [copiedSecret, setCopiedSecret] = useState(false)

  useEffect(() => {
    if (!secret) return
    adminApi.settings(secret)
      .then(setSettings)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [secret])

  async function sendTest() {
    if (!testTo.trim()) return
    setTesting(true)
    setTestResult(null)
    try {
      const r = await adminApi.testEmail(secret, testTo.trim())
      setTestResult(r)
    } catch (e) {
      setTestResult({ sent: false, reason: String(e) })
    } finally {
      setTesting(false)
    }
  }

  function copySecret() {
    navigator.clipboard.writeText(secret)
    setCopiedSecret(true)
    setTimeout(() => setCopiedSecret(false), 2000)
  }

  if (loading || !settings) {
    return <div className="p-8 text-[#94A3B8]">Loading settings…</div>
  }

  const s = settings.smtp

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-8">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <SettingsIcon size={18} className="text-[#00DC82]" />
          Settings
        </h1>
        <p className="text-sm text-[#94A3B8] mt-1">Server configuration and operational status</p>
      </div>

      <div className="space-y-5">
        {/* SMTP */}
        <Section icon={<Mail size={16} />} title="Email (SMTP)" desc="Used for license invite emails. Configure via env vars on the server.">
          <div className="space-y-1">
            <StatusRow
              ok={s.configured}
              label="Configuration"
              value={s.configured ? "Active" : "Not configured"}
            />
            <StatusRow ok={!!s.host}     label="SMTP Host" value={s.host || "—"} />
            <StatusRow ok={s.port > 0}   label="SMTP Port" value={String(s.port)} />
            <StatusRow ok={!!s.user}     label="SMTP User" value={s.user || "—"} />
            <StatusRow ok={!!s.password} label="SMTP Password" value={s.password || "—"} />
            <StatusRow ok={!!s.from}     label="From Address" value={s.from || "—"} />
          </div>

          {!s.configured && (
            <div className="mt-4 bg-amber-900/20 border border-amber-800/40 rounded-lg p-3 text-xs text-amber-300">
              <p className="font-medium mb-1">Set these env vars on the cloud API:</p>
              <pre className="font-mono text-[11px] mt-1 leading-relaxed">
                {`SMTP_HOST=smtp.gmail.com\nSMTP_PORT=587\nSMTP_USER=your-email@example.com\nSMTP_PASS=app-password\nFROM_EMAIL=you@example.com`}
              </pre>
            </div>
          )}

          {/* Test send */}
          <div className="mt-4 pt-4 border-t border-white/8">
            <p className="text-xs text-[#94A3B8] uppercase tracking-wider mb-2">Test Send</p>
            <div className="flex gap-2">
              <input
                value={testTo}
                onChange={e => setTestTo(e.target.value)}
                placeholder="recipient@example.com"
                type="email"
                className="flex-1 bg-[#112233] border border-white/8 rounded-lg px-3 py-2 text-sm text-white placeholder:text-[#94A3B8]/40 outline-none focus:border-[#00DC82]/50 transition-colors"
              />
              <button
                onClick={sendTest}
                disabled={testing || !testTo.trim() || !s.configured}
                className="bg-[#00DC82] text-[#060B14] font-semibold text-sm px-4 py-2 rounded-lg hover:bg-[#00DC82]/90 disabled:opacity-40 transition-colors flex items-center gap-2"
              >
                <Send size={14} /> {testing ? "Sending…" : "Send Test"}
              </button>
            </div>
            {testResult && (
              <div className={`mt-2 text-xs px-3 py-2 rounded-lg border ${testResult.sent ? "bg-emerald-900/20 border-emerald-800/40 text-emerald-300" : "bg-red-900/20 border-red-800/40 text-red-300"}`}>
                {testResult.sent ? `✓ Test email sent to ${testTo}` : `✗ Failed: ${testResult.reason}`}
              </div>
            )}
          </div>
        </Section>

        {/* Admin Secret */}
        <Section icon={<Shield size={16} />} title="Admin Secret" desc="Shared secret for admin API access. Set via PUSHKEY_ADMIN_SECRET env var.">
          <div className="space-y-1">
            <StatusRow
              ok={settings.admin_secret_set}
              label="Custom secret"
              value={settings.admin_secret_set ? "Set (custom)" : "Default — change in production!"}
            />
            <div className="flex items-center justify-between py-2.5">
              <span className="text-sm text-white">Current session secret</span>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm text-[#94A3B8]">
                  {secretShown ? secret : "•".repeat(Math.min(secret.length, 12))}
                </span>
                <button onClick={() => setSecretShown(!secretShown)} className="text-xs text-sky-400 hover:text-sky-300 transition-colors">
                  {secretShown ? "Hide" : "Show"}
                </button>
                <button onClick={copySecret} className="text-[#94A3B8] hover:text-white transition-colors">
                  {copiedSecret ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                </button>
              </div>
            </div>
          </div>
          {!settings.admin_secret_set && (
            <div className="mt-4 bg-red-900/20 border border-red-800/40 rounded-lg p-3 text-xs text-red-300">
              <p className="font-medium mb-1">⚠ Using default secret. Set this before deploying:</p>
              <pre className="font-mono text-[11px] mt-1">PUSHKEY_ADMIN_SECRET=&quot;YourStrongSecret123!&quot;</pre>
            </div>
          )}
        </Section>

        {/* App config */}
        <Section icon={<Database size={16} />} title="Server Status" desc="Runtime info and storage paths.">
          <div className="space-y-1">
            <StatusRow ok={true} label="Cloud API version" value={settings.version} />
            <StatusRow ok={true} label="App URL"           value={settings.app_url} />
            <StatusRow ok={true} label="Data directory"    value={settings.data_dir} />
            <StatusRow ok={true} label="Total licenses"    value={settings.license_count.toLocaleString()} />
            <StatusRow ok={true} label="Event log entries" value={settings.event_count.toLocaleString()} />
          </div>
        </Section>

        {/* Backup */}
        <Section icon={<Download size={16} />} title="Backup" desc="Download all data files (licenses, tickets, audit log, events, users) as tar.gz.">
          <button
            onClick={() => adminApi.downloadBackup(secret).catch(() => {})}
            className="bg-[#00DC82] text-[#060B14] font-semibold text-sm px-4 py-2 rounded-lg hover:bg-[#00DC82]/90 transition-colors flex items-center gap-2"
          >
            <Download size={14} /> Download Backup
          </button>
          <p className="text-xs text-[#94A3B8] mt-3">Excludes encrypted vault blobs (those are zero-knowledge per-user). Schedule this via cron for automated backups.</p>
        </Section>
      </div>
    </div>
  )
}
