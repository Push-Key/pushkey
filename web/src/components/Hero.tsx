"use client"
import { useEffect, useState } from "react"
import { ArrowRight, Download, Lock, RefreshCw, FolderSync, Code2 } from "lucide-react"

const TERMINAL_LINES = [
  { text: "$ pushkey add OPENAI_API_KEY sk-proj-...", delay: 0, color: "#94A3B8" },
  { text: "✓ Provider detected: OpenAI", delay: 600, color: "#00DC82" },
  { text: "✓ Rotation schedule: 90 days", delay: 1000, color: "#00DC82" },
  { text: "✓ Encrypted with AES-256-GCM", delay: 1400, color: "#00DC82" },
  { text: "", delay: 1800, color: "#94A3B8" },
  { text: "$ pushkey inject --project ./my-app", delay: 2000, color: "#94A3B8" },
  { text: "✓ Writing .env to ./my-app/.env", delay: 2600, color: "#00DC82" },
  { text: "✓ Added OPENAI_API_KEY to .gitignore", delay: 3000, color: "#00DC82" },
  { text: "✓ 3 projects synced", delay: 3400, color: "#00DC82" },
]

function TerminalWindow() {
  const [visibleLines, setVisibleLines] = useState<number[]>([])

  useEffect(() => {
    TERMINAL_LINES.forEach((line, i) => {
      setTimeout(() => setVisibleLines(prev => [...prev, i]), line.delay + 800)
    })
  }, [])

  return (
    <div className="rounded-xl overflow-hidden" style={{ background: "#0D1B2A", border: "1px solid rgba(255,255,255,0.1)" }}>
      {/* Traffic lights */}
      <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: "1px solid rgba(255,255,255,0.08)", background: "#0A1624" }}>
        <div className="w-3 h-3 rounded-full" style={{ background: "#FF5F57" }} />
        <div className="w-3 h-3 rounded-full" style={{ background: "#FFBD2E" }} />
        <div className="w-3 h-3 rounded-full" style={{ background: "#28C840" }} />
        <span className="ml-2 text-xs font-mono" style={{ color: "#64748B" }}>pushkey — vault</span>
      </div>
      <div className="p-4 font-mono text-sm min-h-[220px]">
        {TERMINAL_LINES.map((line, i) => (
          visibleLines.includes(i) ? (
            <div key={i} className="leading-7 transition-all duration-300" style={{ color: line.color }}>
              {line.text || " "}
            </div>
          ) : null
        ))}
        {visibleLines.length < TERMINAL_LINES.length && (
          <span className="animate-pulse" style={{ color: "#00DC82" }}>█</span>
        )}
      </div>
    </div>
  )
}

export default function Hero() {
  return (
    <section className="hero-gradient min-h-screen flex items-center pt-20 pb-16">
      <div className="max-w-7xl mx-auto px-6 w-full">
        <div className="grid lg:grid-cols-2 gap-16 items-center">
          {/* Left: Copy */}
          <div>
            <div className="flex flex-wrap items-center gap-3 mb-6">
              <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-mono"
                style={{ background: "rgba(0,220,130,0.1)", border: "1px solid rgba(0,220,130,0.25)", color: "#00DC82" }}>
                <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
                AES-256-GCM · Zero network access
              </div>
              <a href="https://github.com/ebothegreat/pushkey" target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-mono transition-all"
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.12)", color: "#94A3B8" }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.3)"; e.currentTarget.style.color = "#F8FAFC" }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.12)"; e.currentTarget.style.color = "#94A3B8" }}>
                <Code2 size={11} />
                Open source — audit the vault
                <ArrowRight size={10} />
              </a>
            </div>

            <h1 className="text-5xl lg:text-6xl xl:text-7xl font-bold leading-tight tracking-tight mb-6"
              style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
              Your secrets.{" "}
              <span style={{ color: "#00DC82" }}>Encrypted.</span>
              <br />
              Where you{" "}
              <span style={{ background: "linear-gradient(135deg, #7C3AED, #A78BFA)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                need them.
              </span>
            </h1>

            <p className="text-lg leading-relaxed mb-8" style={{ color: "#94A3B8", maxWidth: "520px" }}>
              PushKey stores your API keys encrypted, tracks rotation health, and automatically writes{" "}
              <code className="font-mono text-sm px-1.5 py-0.5 rounded" style={{ background: "rgba(255,255,255,0.08)", color: "#F8FAFC" }}>.env</code>
              {" "}files into every linked project. No copy-paste. No leaks. No forgotten rotations.
            </p>

            <div className="flex flex-wrap gap-4 mb-12">
              <a href="#pricing"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-semibold text-sm transition-all glow-green"
                style={{ background: "#00DC82", color: "#060B14" }}
                onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.opacity = "0.92" }}
                onMouseLeave={e => { e.currentTarget.style.transform = ""; e.currentTarget.style.opacity = "1" }}>
                <Download size={16} />
                Download Free
              </a>
              <a href="#features"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-semibold text-sm transition-all"
                style={{ background: "rgba(255,255,255,0.06)", color: "#F8FAFC", border: "1px solid rgba(255,255,255,0.12)" }}
                onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.1)" }}
                onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.06)" }}>
                See how it works <ArrowRight size={16} />
              </a>
            </div>

            {/* Social proof */}
            <div className="flex items-center gap-6 text-sm" style={{ color: "#64748B" }}>
              <div className="flex items-center gap-1.5">
                <Lock size={12} style={{ color: "#00DC82" }} />
                No cloud, no tracking
              </div>
              <div className="flex items-center gap-1.5">
                <RefreshCw size={12} style={{ color: "#00DC82" }} />
                Auto-rotation alerts
              </div>
              <div className="flex items-center gap-1.5">
                <FolderSync size={12} style={{ color: "#00DC82" }} />
                Direct .env injection
              </div>
            </div>
          </div>

          {/* Right: Terminal */}
          <div>
            <TerminalWindow />

            {/* Key health preview below terminal */}
            <div className="mt-4 grid grid-cols-3 gap-3">
              {[
                { name: "OPENAI_API_KEY", status: "green", age: "12d" },
                { name: "STRIPE_SECRET", status: "amber", age: "67d" },
                { name: "OANDA_TOKEN", status: "red", age: "94d" },
              ].map(key => (
                <div key={key.name} className="rounded-lg p-3" style={{ background: "#0D1B2A", border: "1px solid rgba(255,255,255,0.08)" }}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full" style={{
                      background: key.status === "green" ? "#00DC82" : key.status === "amber" ? "#F59E0B" : "#EF4444",
                      boxShadow: `0 0 6px ${key.status === "green" ? "#00DC82" : key.status === "amber" ? "#F59E0B" : "#EF4444"}`
                    }} />
                    <span className="text-xs font-mono truncate" style={{ color: "#64748B" }}>{key.name}</span>
                  </div>
                  <span className="text-xs" style={{ color: "#94A3B8" }}>Last rotated {key.age} ago</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
