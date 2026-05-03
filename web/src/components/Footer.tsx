"use client"
import { Shield, ExternalLink } from "lucide-react"

const PRODUCT_LINKS: { label: string; href: string }[] = [
  { label: "Features", href: "#features" },
  { label: "Security", href: "#security" },
  { label: "Pricing", href: "#pricing" },
  { label: "Changelog", href: "https://github.com/Push-Key/pushkey/releases" },
  { label: "Roadmap", href: "https://github.com/Push-Key/pushkey/issues" },
]

const INTEGRATION_LINKS: { label: string; href: string }[] = [
  { label: "GitHub Actions", href: "https://github.com/Push-Key/pushkey#ci-cd" },
  { label: "Vercel", href: "https://github.com/Push-Key/pushkey#vercel" },
  { label: "Railway", href: "https://github.com/Push-Key/pushkey#railway" },
  { label: "VS Code Extension", href: "https://github.com/Push-Key/pushkey/tree/main/vscode-pushkey" },
  { label: "25+ Providers", href: "#features" },
]

const LEGAL_LINKS: { label: string; href: string }[] = [
  { label: "Privacy Policy", href: "/privacy" },
  { label: "Terms of Service", href: "/terms" },
  { label: "License (MIT)", href: "https://github.com/Push-Key/pushkey/blob/main/LICENSE" },
  { label: "Security Policy", href: "https://github.com/Push-Key/pushkey/blob/main/SECURITY.md" },
]

export default function Footer() {
  return (
    <footer style={{ borderTop: "1px solid rgba(255,255,255,0.06)", background: "#060B14" }}>
      <div className="max-w-7xl mx-auto px-6 py-12">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-8 mb-12">
          {/* Brand */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: "rgba(0,220,130,0.15)", border: "1px solid rgba(0,220,130,0.3)" }}>
                <Shield size={14} style={{ color: "#00DC82" }} />
              </div>
              <span className="font-bold">PushKey</span>
            </div>
            <p className="text-sm leading-relaxed" style={{ color: "#64748B" }}>
              Encrypted API key vault with direct .env injection. Local-first. Open source. Free to start.
            </p>
            <div className="flex gap-3 mt-4">
              <a href="https://github.com/Push-Key/pushkey" target="_blank" rel="noopener noreferrer"
                className="transition-colors text-xs font-mono flex items-center gap-1" style={{ color: "#64748B" }}
                onMouseEnter={e => (e.currentTarget.style.color = "#F8FAFC")}
                onMouseLeave={e => (e.currentTarget.style.color = "#64748B")}>
                <ExternalLink size={14} />
                GitHub
              </a>
            </div>
          </div>

          {/* Product */}
          <div>
            <h4 className="text-sm font-semibold mb-4">Product</h4>
            <ul className="space-y-2.5">
              {PRODUCT_LINKS.map(({ label, href }) => (
                <li key={label}>
                  <a href={href} target={href.startsWith("http") ? "_blank" : undefined}
                    rel={href.startsWith("http") ? "noopener noreferrer" : undefined}
                    className="text-sm transition-colors" style={{ color: "#64748B" }}
                    onMouseEnter={e => (e.currentTarget.style.color = "#94A3B8")}
                    onMouseLeave={e => (e.currentTarget.style.color = "#64748B")}>
                    {label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          {/* Integrations */}
          <div>
            <h4 className="text-sm font-semibold mb-4">Integrations</h4>
            <ul className="space-y-2.5">
              {INTEGRATION_LINKS.map(({ label, href }) => (
                <li key={label}>
                  <a href={href} target={href.startsWith("http") ? "_blank" : undefined}
                    rel={href.startsWith("http") ? "noopener noreferrer" : undefined}
                    className="text-sm transition-colors" style={{ color: "#64748B" }}
                    onMouseEnter={e => (e.currentTarget.style.color = "#94A3B8")}
                    onMouseLeave={e => (e.currentTarget.style.color = "#64748B")}>
                    {label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          {/* Legal */}
          <div>
            <h4 className="text-sm font-semibold mb-4">Legal</h4>
            <ul className="space-y-2.5">
              {LEGAL_LINKS.map(({ label, href }) => (
                <li key={label}>
                  <a href={href} target={href.startsWith("http") ? "_blank" : undefined}
                    rel={href.startsWith("http") ? "noopener noreferrer" : undefined}
                    className="text-sm transition-colors" style={{ color: "#64748B" }}
                    onMouseEnter={e => (e.currentTarget.style.color = "#94A3B8")}
                    onMouseLeave={e => (e.currentTarget.style.color = "#64748B")}>
                    {label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row justify-between items-center gap-4 pt-8"
          style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
          <p className="text-xs" style={{ color: "#334155" }}>
            © 2025 PushKey. MIT License. Built for engineers.
          </p>
          <div className="flex items-center gap-1.5 text-xs font-mono" style={{ color: "#334155" }}>
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: "#00DC82" }} />
            Local-first · Zero telemetry · Open source
          </div>
        </div>
      </div>
    </footer>
  )
}
