"use client"
import { Shield, Lock, GitBranch, Code2, Clipboard, Wifi } from "lucide-react"

const TRUST = [
  { icon: Shield, label: "AES-256-GCM Encryption" },
  { icon: Lock, label: "Argon2id Key Derivation" },
  { icon: Wifi, label: "Zero Network Access" },
  { icon: GitBranch, label: "Git History Scanner" },
  { icon: Clipboard, label: "Auto-clear Clipboard" },
  { icon: Code2, label: "Open Source Core" },
]

export default function TrustBar() {
  return (
    <div className="py-6" style={{ borderTop: "1px solid rgba(255,255,255,0.06)", borderBottom: "1px solid rgba(255,255,255,0.06)", background: "rgba(13,27,42,0.5)" }}>
      <div className="max-w-7xl mx-auto px-6">
        <div className="flex flex-wrap justify-center gap-8 md:gap-12">
          {TRUST.map(({ icon: Icon, label }) => (
            <div key={label} className="flex items-center gap-2.5">
              <Icon size={14} style={{ color: "#00DC82" }} />
              <span className="text-sm font-mono" style={{ color: "#64748B" }}>{label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
