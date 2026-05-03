"use client"
import {
  ShieldCheck, RefreshCw, FolderSync, Link2, GitBranch, Cloud,
  Users, KeyRound, Lock, Code2, Fingerprint, Eye
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

const FEATURES: { icon: LucideIcon; title: string; desc: string; accent: string }[] = [
  { icon: ShieldCheck, title: "AES-256-GCM Vault", desc: "Strong local encryption with AES-256-GCM and Argon2id key derivation. 200,000 iterations. Your keys never leave your machine.", accent: "#00DC82" },
  { icon: FolderSync, title: "Direct .env Injection", desc: "When you rotate or add a key, Pushkey writes the updated .env file into every linked project folder — instantly.", accent: "#00DC82" },
  { icon: RefreshCw, title: "Rotation Health Tracking", desc: "Green / yellow / red status dots. See at a glance which keys are fresh, aging, or overdue for rotation.", accent: "#00DC82" },
  { icon: Link2, title: "Provider Dashboard Links", desc: "One click opens the exact page to generate a new key for 25+ providers: OpenAI, Stripe, AWS, Vercel, and more.", accent: "#A78BFA" },
  { icon: GitBranch, title: "Git History Scanner", desc: "Scans your commit history for accidentally committed secrets. Flags exposed keys before they become a breach.", accent: "#A78BFA" },
  { icon: Cloud, title: "CI/CD Sync", desc: "Push secrets to GitHub Actions, Vercel environment variables, and Railway directly from the vault — no copy-paste in CI.", accent: "#A78BFA" },
  { icon: Users, title: "Team RBAC", desc: "Share vaults with your team. Role-based access control — admins set policies, devs get read-only access to their keys.", accent: "#F59E0B" },
  { icon: KeyRound, title: "TOTP MFA", desc: "Two-factor authentication on vault unlock. Works with any TOTP app (Authy, Google Authenticator, 1Password).", accent: "#F59E0B" },
  { icon: Lock, title: "Clipboard Auto-clear", desc: "Copied keys automatically cleared from clipboard after 30 seconds. Revealed keys auto-hide after 10 seconds.", accent: "#00DC82" },
  { icon: Code2, title: "Open Source Core", desc: "The crypto layer and vault are MIT licensed. Audit every line that touches your keys — no trust required.", accent: "#A78BFA" },
  { icon: Fingerprint, title: "Hardware MFA (Enterprise)", desc: "YubiKey and hardware security key support for vaults that need the highest level of authentication assurance.", accent: "#F59E0B" },
  { icon: Eye, title: "Encrypted Audit Log", desc: "Every vault access, key rotation, and team action is logged in an encrypted audit trail for compliance.", accent: "#F59E0B" },
]

export default function Features() {
  return (
    <section id="security" className="py-24" style={{ background: "rgba(13,27,42,0.3)" }}>
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <div className="inline-block text-xs font-mono px-3 py-1 rounded-full mb-4"
            style={{ background: "rgba(0,220,130,0.1)", border: "1px solid rgba(0,220,130,0.25)", color: "#00DC82" }}>
            FEATURES
          </div>
          <h2 className="text-4xl lg:text-5xl font-bold tracking-tight mb-4" style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
            Everything your team needs to keep secrets safe
          </h2>
          <p className="text-lg max-w-xl mx-auto" style={{ color: "#94A3B8" }}>
            Not a password manager. Not a cloud secrets service. PushKey is a local-first vault built for engineers who care about security.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {FEATURES.map(({ icon: Icon, title, desc, accent }) => (
            <div key={title} className="rounded-xl p-5 transition-all duration-200 group cursor-default"
              style={{ background: "#0D1B2A", border: "1px solid rgba(255,255,255,0.06)" }}
              onMouseEnter={e => { e.currentTarget.style.border = `1px solid ${accent}30`; e.currentTarget.style.background = "#112233" }}
              onMouseLeave={e => { e.currentTarget.style.border = "1px solid rgba(255,255,255,0.06)"; e.currentTarget.style.background = "#0D1B2A" }}>
              <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-3"
                style={{ background: `${accent}15`, border: `1px solid ${accent}30` }}>
                <Icon size={16} style={{ color: accent }} />
              </div>
              <h3 className="font-semibold text-sm mb-2">{title}</h3>
              <p className="text-xs leading-relaxed" style={{ color: "#64748B" }}>{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
