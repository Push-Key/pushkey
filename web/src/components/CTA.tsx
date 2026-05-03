"use client"
import { Download, ArrowRight } from "lucide-react"

export default function CTA() {
  return (
    <section className="py-24">
      <div className="max-w-7xl mx-auto px-6">
        <div className="rounded-2xl p-12 lg:p-20 text-center relative overflow-hidden"
          style={{ background: "linear-gradient(135deg, rgba(124,58,237,0.15) 0%, rgba(0,220,130,0.08) 100%)", border: "1px solid rgba(124,58,237,0.25)" }}>
          {/* Background orbs */}
          <div className="absolute top-0 left-1/4 w-64 h-64 rounded-full pointer-events-none"
            style={{ background: "radial-gradient(circle, rgba(124,58,237,0.15) 0%, transparent 70%)" }} />
          <div className="absolute bottom-0 right-1/4 w-64 h-64 rounded-full pointer-events-none"
            style={{ background: "radial-gradient(circle, rgba(0,220,130,0.1) 0%, transparent 70%)" }} />

          <div className="relative z-10">
            <div className="inline-block font-mono text-xs px-3 py-1 rounded-full mb-6"
              style={{ background: "rgba(0,220,130,0.1)", border: "1px solid rgba(0,220,130,0.3)", color: "#00DC82" }}>
              FREE TO START · NO CREDIT CARD REQUIRED
            </div>
            <h2 className="text-4xl lg:text-5xl font-bold tracking-tight mb-4" style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
              Stop storing secrets in Slack.<br />
              <span style={{ color: "#00DC82" }}>Start using PushKey.</span>
            </h2>
            <p className="text-lg mb-10 max-w-lg mx-auto" style={{ color: "#94A3B8" }}>
              15 keys, 1 project, full encryption — free forever. Upgrade only when your team needs it.
            </p>

            <div className="flex flex-wrap justify-center gap-4">
              <a href="https://github.com/Push-Key/pushkey/releases" target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-semibold text-sm transition-all glow-green"
                style={{ background: "#00DC82", color: "#060B14" }}
                onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.opacity = "0.92" }}
                onMouseLeave={e => { e.currentTarget.style.transform = ""; e.currentTarget.style.opacity = "1" }}>
                <Download size={16} />
                Download PushKey Free
              </a>
              <a href={process.env.NEXT_PUBLIC_STRIPE_LIFETIME || "mailto:hello@push-key.com?subject=Lifetime Deal"} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-semibold text-sm transition-all"
                style={{ background: "rgba(251,191,36,0.1)", color: "#FBBF24", border: "1px solid rgba(251,191,36,0.3)" }}
                onMouseEnter={e => { e.currentTarget.style.background = "rgba(251,191,36,0.18)" }}
                onMouseLeave={e => { e.currentTarget.style.background = "rgba(251,191,36,0.1)" }}>
                🔑 Get Lifetime Deal — $149
              </a>
              <a href="mailto:hello@push-key.com"
                className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-semibold text-sm transition-all"
                style={{ background: "rgba(255,255,255,0.06)", color: "#F8FAFC", border: "1px solid rgba(255,255,255,0.12)" }}
                onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.1)" }}
                onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.06)" }}>
                Talk to sales <ArrowRight size={16} />
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
