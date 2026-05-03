"use client"
import { useState } from "react"
import { FileText, Copy, Check, Terminal, Cloud, Key, Activity } from "lucide-react"

function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="relative group">
      <pre className="bg-[#060B14] border border-white/8 rounded-lg p-4 text-xs font-mono text-[#94A3B8] overflow-x-auto">
        {lang && <span className="text-[10px] text-[#475569] uppercase tracking-widest mb-2 block">{lang}</span>}
        <code>{code}</code>
      </pre>
      <button
        onClick={() => {
          navigator.clipboard.writeText(code)
          setCopied(true)
          setTimeout(() => setCopied(false), 2000)
        }}
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-[#94A3B8] hover:text-white p-1.5 bg-[#0D1B2A] border border-white/10 rounded transition-opacity"
      >
        {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
      </button>
    </div>
  )
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="bg-[#0D1B2A] border border-white/8 rounded-xl p-5">
      <div className="flex items-center gap-2.5 mb-4">
        <span className="text-[#00DC82]">{icon}</span>
        <p className="font-semibold text-white">{title}</p>
      </div>
      <div className="space-y-3 text-sm text-[#94A3B8]">{children}</div>
    </div>
  )
}

function Endpoint({ method, path, desc }: { method: string; path: string; desc: string }) {
  const colors: Record<string, string> = {
    GET:    "text-emerald-400 bg-emerald-900/30 border-emerald-800/40",
    POST:   "text-sky-400    bg-sky-900/30    border-sky-800/40",
    PATCH:  "text-amber-400  bg-amber-900/30  border-amber-800/40",
    PUT:    "text-violet-400 bg-violet-900/30 border-violet-800/40",
    DELETE: "text-red-400    bg-red-900/30    border-red-800/40",
  }
  return (
    <div className="flex items-center gap-3 py-2 border-b border-white/5 last:border-b-0">
      <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${colors[method] ?? "border-white/10"} font-mono w-14 text-center`}>
        {method}
      </span>
      <code className="text-xs text-sky-400 font-mono flex-shrink-0">{path}</code>
      <span className="text-xs text-[#94A3B8] truncate">{desc}</span>
    </div>
  )
}

export default function DocsPage() {
  return (
    <div className="p-8 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <FileText size={18} className="text-[#00DC82]" />
          API Documentation
        </h1>
        <p className="text-sm text-[#94A3B8] mt-1">Endpoints, CLI usage, and integration guide</p>
      </div>

      <div className="space-y-5">
        {/* Auth */}
        <Section icon={<Key size={16} />} title="Authentication">
          <p>Admin endpoints require the <code className="text-sky-400 bg-[#060B14] px-1 py-0.5 rounded">X-Admin-Secret</code> header.</p>
          <CodeBlock lang="curl" code={`curl https://api.pushkey.app/api/admin/licenses \\
  -H "X-Admin-Secret: YourSecretHere"`} />
          <p>Client endpoints (heartbeat) require a valid license key in the request body. No auth header needed.</p>
        </Section>

        {/* Client API */}
        <Section icon={<Cloud size={16} />} title="Client API (consumed by desktop app)">
          <div className="border border-white/8 rounded-lg overflow-hidden">
            <Endpoint method="POST" path="/v1/heartbeat"           desc="Client liveness ping (also /api/v1/heartbeat alias)" />
            <Endpoint method="POST" path="/api/v1/auth/register"   desc="Register new cloud sync user" />
            <Endpoint method="POST" path="/api/v1/auth/login"      desc="Login, returns JWT" />
            <Endpoint method="PUT"  path="/api/v1/vault"           desc="Upload encrypted vault blob" />
            <Endpoint method="GET"  path="/api/v1/vault"           desc="Download encrypted vault blob" />
            <Endpoint method="GET"  path="/api/v1/vault/meta"      desc="Vault metadata (size, etag, modified)" />
            <Endpoint method="GET"  path="/api/v1/health"          desc="Server health check" />
          </div>
          <CodeBlock lang="curl" code={`curl -X POST https://api.pushkey.app/v1/heartbeat \\
  -H "Content-Type: application/json" \\
  -d '{"license_key":"PRO-XXXX-XXXX-XXXX","platform":"Windows 11","version":"1.0.3"}'`} />
        </Section>

        {/* Admin API */}
        <Section icon={<Activity size={16} />} title="Admin API">
          <div className="border border-white/8 rounded-lg overflow-hidden">
            <Endpoint method="GET"   path="/api/admin/stats"                   desc="Total/active/revoked counts + deltas" />
            <Endpoint method="GET"   path="/api/admin/licenses"                desc="List all license records" />
            <Endpoint method="POST"  path="/api/admin/licenses/generate"       desc="Quick-generate (no email/CRM)" />
            <Endpoint method="POST"  path="/api/admin/licenses/issue"          desc="Full issue with CRM + invite email" />
            <Endpoint method="POST"  path="/api/admin/licenses/{key}/expire"   desc="Mark license expired" />
            <Endpoint method="POST"  path="/api/admin/licenses/{key}/revoke"   desc="Revoke license" />
            <Endpoint method="POST"  path="/api/admin/licenses/{key}/renew"    desc="Reactivate license" />
            <Endpoint method="POST"  path="/api/admin/licenses/{key}/send-invite" desc="Resend invite email" />
            <Endpoint method="GET"   path="/api/admin/contacts"                desc="Contacts grouped by email (CRM view)" />
            <Endpoint method="PATCH" path="/api/admin/contacts/{email}"        desc="Update contact fields" />
            <Endpoint method="GET"   path="/api/admin/analytics"               desc="30-day time-series + event totals" />
            <Endpoint method="GET"   path="/api/admin/audit"                   desc="Admin action audit log" />
            <Endpoint method="GET"   path="/api/admin/settings"                desc="Server config status" />
            <Endpoint method="POST"  path="/api/admin/settings/test-email"     desc="Send test email" />
            <Endpoint method="GET"   path="/api/admin/export"                  desc="CSV export of all licenses" />
          </div>
        </Section>

        {/* CLI */}
        <Section icon={<Terminal size={16} />} title="Pushkey CLI — for CI/CD">
          <p>The desktop app is paired with a CLI (<code className="text-sky-400 bg-[#060B14] px-1 py-0.5 rounded">pushkey-cli.exe</code> or <code className="text-sky-400 bg-[#060B14] px-1 py-0.5 rounded">pushkey</code>) that handles CI/CD use cases <strong>without server round-trips</strong> — keeping the zero-knowledge model.</p>

          <p className="mt-4 text-white font-medium">Inject keys into a project&apos;s .env:</p>
          <CodeBlock code={`pushkey inject --env prod`} />

          <p className="mt-4 text-white font-medium">Export keys for CI:</p>
          <CodeBlock code={`# Dotenv format
pushkey export --format dotenv --env prod -o .env.production

# JSON format
pushkey export --format json --env prod | jq .`} />

          <p className="mt-4 text-white font-medium">GitHub Actions example:</p>
          <CodeBlock lang="yaml" code={`- name: Inject API keys
  env:
    PUSHKEY_PASSWORD: \${{ secrets.PUSHKEY_PASSWORD }}
  run: |
    pushkey export --format dotenv --env prod >> $GITHUB_ENV`} />

          <p className="mt-4 text-xs text-[#94A3B8] italic">CLI uses the local vault — vault file must be present in the runner. For ephemeral runners, mount the vault from CI secrets.</p>
        </Section>

        {/* Tier limits reference */}
        <Section icon={<Key size={16} />} title="Tier Limits Reference">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/8 text-[#94A3B8]">
                  <th className="text-left py-2 pr-3">Tier</th>
                  <th className="text-left py-2 pr-3">Max Keys</th>
                  <th className="text-left py-2 pr-3">Max Projects</th>
                  <th className="text-left py-2 pr-3">Max Devices</th>
                  <th className="text-left py-2 pr-3">Cloud Sync</th>
                  <th className="text-left py-2 pr-3">CI Sync</th>
                  <th className="text-left py-2 pr-3">Team RBAC</th>
                </tr>
              </thead>
              <tbody className="text-white">
                <tr className="border-b border-white/5"><td className="py-2 pr-3">🔲 Free</td><td>15</td><td>1</td><td>1</td><td>—</td><td>—</td><td>—</td></tr>
                <tr className="border-b border-white/5"><td className="py-2 pr-3">🚀 Starter</td><td>50</td><td>3</td><td>1</td><td>✓</td><td>—</td><td>—</td></tr>
                <tr className="border-b border-white/5"><td className="py-2 pr-3">⚡ Pro</td><td>∞</td><td>∞</td><td>3</td><td>✓</td><td>✓</td><td>—</td></tr>
                <tr className="border-b border-white/5"><td className="py-2 pr-3">👥 Team</td><td>∞</td><td>∞</td><td>5</td><td>✓</td><td>✓</td><td>✓</td></tr>
                <tr className="border-b border-white/5"><td className="py-2 pr-3">🏛️ Enterprise</td><td>∞</td><td>∞</td><td>∞</td><td>✓</td><td>✓</td><td>✓</td></tr>
              </tbody>
            </table>
          </div>
          <p className="text-xs italic">Limits enforced in desktop app, not server-side. Tier embedded in license key prefix.</p>
        </Section>

        {/* Webhook */}
        <Section icon={<Cloud size={16} />} title="Server Heartbeat Behavior">
          <p>The desktop app calls <code className="text-sky-400 bg-[#060B14] px-1 py-0.5 rounded">/v1/heartbeat</code> at most once per 24 hours after vault unlock.</p>
          <ul className="list-disc list-inside space-y-1 text-xs">
            <li>If server unreachable, app uses cached token within 10-day grace window</li>
            <li>After grace expires, app downgrades to Free tier features</li>
            <li>Server response includes current tier + status, allowing remote downgrade</li>
            <li>Revoked licenses get a 403 response → app blocks all paid features immediately</li>
          </ul>
        </Section>
      </div>
    </div>
  )
}
