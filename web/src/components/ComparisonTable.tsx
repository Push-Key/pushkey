import { Check, X, Minus } from "lucide-react"

type Support = "yes" | "no" | "partial"

interface Competitor {
  name: string
  note?: string
}

interface Feature {
  category: string
  label: string
  pushkey: Support
  competitors: Record<string, Support>
}

const COMPETITORS: Competitor[] = [
  { name: "Doppler" },
  { name: "1Password Secrets" },
  { name: "Infisical" },
  { name: "dotenv vault" },
]

const FEATURES: Feature[] = [
  {
    category: "Security",
    label: "AES-256-GCM encryption",
    pushkey: "yes",
    competitors: { Doppler: "yes", "1Password Secrets": "yes", Infisical: "yes", "dotenv vault": "partial" },
  },
  {
    category: "Security",
    label: "Argon2id key derivation",
    pushkey: "yes",
    competitors: { Doppler: "no", "1Password Secrets": "partial", Infisical: "no", "dotenv vault": "no" },
  },
  {
    category: "Security",
    label: "Zero-knowledge cloud sync",
    pushkey: "yes",
    competitors: { Doppler: "no", "1Password Secrets": "no", Infisical: "partial", "dotenv vault": "partial" },
  },
  {
    category: "Workflow",
    label: "Works 100% offline",
    pushkey: "yes",
    competitors: { Doppler: "no", "1Password Secrets": "no", Infisical: "no", "dotenv vault": "no" },
  },
  {
    category: "Workflow",
    label: "Auto-detects provider from key name",
    pushkey: "yes",
    competitors: { Doppler: "no", "1Password Secrets": "no", Infisical: "no", "dotenv vault": "no" },
  },
  {
    category: "Workflow",
    label: "Auto-injects to .env files",
    pushkey: "yes",
    competitors: { Doppler: "yes", "1Password Secrets": "partial", Infisical: "yes", "dotenv vault": "yes" },
  },
  {
    category: "Workflow",
    label: "Built-in rotation scheduling",
    pushkey: "yes",
    competitors: { Doppler: "partial", "1Password Secrets": "no", Infisical: "partial", "dotenv vault": "no" },
  },
  {
    category: "Access",
    label: "Native desktop GUI app",
    pushkey: "yes",
    competitors: { Doppler: "no", "1Password Secrets": "no", Infisical: "no", "dotenv vault": "no" },
  },
  {
    category: "Access",
    label: "Full-featured CLI (scriptable, CI-ready)",
    pushkey: "yes",
    competitors: { Doppler: "yes", "1Password Secrets": "yes", Infisical: "yes", "dotenv vault": "partial" },
  },
  {
    category: "Access",
    label: "GUI + CLI — both available",
    pushkey: "yes",
    competitors: { Doppler: "no", "1Password Secrets": "no", Infisical: "no", "dotenv vault": "no" },
  },
  {
    category: "Access",
    label: "Free tier with full encryption",
    pushkey: "yes",
    competitors: { Doppler: "partial", "1Password Secrets": "no", Infisical: "yes", "dotenv vault": "partial" },
  },
  {
    category: "Access",
    label: "No SaaS dependency to get started",
    pushkey: "yes",
    competitors: { Doppler: "no", "1Password Secrets": "no", Infisical: "no", "dotenv vault": "no" },
  },
]

function SupportIcon({ value }: { value: Support }) {
  if (value === "yes") return <Check size={16} style={{ color: "#00DC82" }} strokeWidth={2.5} />
  if (value === "no") return <X size={16} style={{ color: "#64748B" }} strokeWidth={2} />
  return <Minus size={16} style={{ color: "#F59E0B" }} strokeWidth={2} />
}

const CATEGORIES = [...new Set(FEATURES.map((f) => f.category))]

export default function ComparisonTable() {
  return (
    <section id="comparison" className="py-24">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <div
            className="inline-block text-xs font-mono px-3 py-1 rounded-full mb-4"
            style={{
              background: "rgba(0,220,130,0.08)",
              border: "1px solid rgba(0,220,130,0.2)",
              color: "#00DC82",
            }}
          >
            VS THE COMPETITION
          </div>
          <h2
            className="text-4xl lg:text-5xl font-bold tracking-tight mb-4"
            style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}
          >
            Why developers choose PushKey
          </h2>
          <p className="text-lg max-w-xl mx-auto" style={{ color: "#94A3B8" }}>
            The only secrets manager that's local-first, provider-aware, and doesn't require a cloud account to start.
          </p>
        </div>

        <div className="overflow-x-auto rounded-xl" style={{ border: "1px solid rgba(255,255,255,0.08)" }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: "#0D1B2A", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                <th className="text-left px-5 py-4 font-semibold" style={{ color: "#94A3B8", minWidth: 220 }}>
                  Feature
                </th>
                {/* PushKey column */}
                <th className="px-5 py-4 font-bold text-center" style={{ minWidth: 120 }}>
                  <div
                    className="inline-flex flex-col items-center gap-1 px-3 py-1.5 rounded-lg"
                    style={{ background: "rgba(0,220,130,0.1)", border: "1px solid rgba(0,220,130,0.25)" }}
                  >
                    <span style={{ color: "#00DC82", fontSize: 13 }}>PushKey</span>
                    <span className="text-xs font-mono" style={{ color: "rgba(0,220,130,0.6)", fontSize: 10 }}>
                      YOU ARE HERE
                    </span>
                  </div>
                </th>
                {COMPETITORS.map((c) => (
                  <th
                    key={c.name}
                    className="px-5 py-4 font-medium text-center"
                    style={{ color: "#64748B", minWidth: 120 }}
                  >
                    {c.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CATEGORIES.map((cat) => {
                const rows = FEATURES.filter((f) => f.category === cat)
                return rows.map((feature, i) => (
                  <tr
                    key={feature.label}
                    style={{
                      background: i % 2 === 0 ? "#060B14" : "#080F1A",
                      borderBottom: "1px solid rgba(255,255,255,0.04)",
                    }}
                  >
                    <td className="px-5 py-3.5">
                      {i === 0 && (
                        <span
                          className="inline-block text-xs font-mono px-2 py-0.5 rounded mb-1"
                          style={{ background: "rgba(124,58,237,0.12)", color: "#A78BFA" }}
                        >
                          {cat}
                        </span>
                      )}
                      <div style={{ color: "#E2E8F0" }}>{feature.label}</div>
                    </td>
                    {/* PushKey */}
                    <td className="px-5 py-3.5 text-center">
                      <div
                        className="inline-flex items-center justify-center w-7 h-7 rounded-full"
                        style={{ background: "rgba(0,220,130,0.1)" }}
                      >
                        <SupportIcon value={feature.pushkey} />
                      </div>
                    </td>
                    {COMPETITORS.map((c) => (
                      <td key={c.name} className="px-5 py-3.5 text-center">
                        <div className="inline-flex items-center justify-center w-7 h-7 rounded-full">
                          <SupportIcon value={feature.competitors[c.name]} />
                        </div>
                      </td>
                    ))}
                  </tr>
                ))
              })}
            </tbody>
          </table>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-6 mt-4 px-1" style={{ color: "#64748B", fontSize: 12 }}>
          <span className="flex items-center gap-1.5">
            <Check size={13} style={{ color: "#00DC82" }} strokeWidth={2.5} /> Fully supported
          </span>
          <span className="flex items-center gap-1.5">
            <Minus size={13} style={{ color: "#F59E0B" }} strokeWidth={2} /> Partial / paid tier only
          </span>
          <span className="flex items-center gap-1.5">
            <X size={13} style={{ color: "#64748B" }} strokeWidth={2} /> Not supported
          </span>
        </div>
      </div>
    </section>
  )
}
