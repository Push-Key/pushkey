import { PlusCircle, FolderOpen, Zap } from "lucide-react"
import type { LucideIcon } from "lucide-react"

const STEPS: { number: string; icon: LucideIcon; title: string; description: string; code: string }[] = [
  {
    number: "01",
    icon: PlusCircle,
    title: "Add your keys",
    description: "Paste your API key with a name like OPENAI_API_KEY. PushKey auto-detects the provider, sets the rotation schedule, and encrypts it with AES-256-GCM.",
    code: `$ pushkey add STRIPE_SECRET_KEY sk_live_...\n✓ Provider: Stripe\n✓ Rotation: 180 days\n✓ Encrypted and stored`,
  },
  {
    number: "02",
    icon: FolderOpen,
    title: "Link your projects",
    description: "Point to your project folders. Assign which keys each project needs. PushKey knows exactly which secrets go where.",
    code: `$ pushkey link ./my-app STRIPE_SECRET_KEY\n✓ Project registered\n✓ .env template created\n✓ Added to .gitignore`,
  },
  {
    number: "03",
    icon: Zap,
    title: "Auto-sync on rotation",
    description: "When you rotate a key, PushKey saves the old value, timestamps the rotation, and pushes the new .env to every linked project instantly.",
    code: `$ pushkey rotate STRIPE_SECRET_KEY\n✓ Old value backed up\n✓ 3 projects updated\n✓ Sync complete in 0.2s`,
  },
]

export default function HowItWorks() {
  return (
    <section id="features" className="py-24">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <div className="inline-block text-xs font-mono px-3 py-1 rounded-full mb-4"
            style={{ background: "rgba(124,58,237,0.1)", border: "1px solid rgba(124,58,237,0.25)", color: "#A78BFA" }}>
            HOW IT WORKS
          </div>
          <h2 className="text-4xl lg:text-5xl font-bold tracking-tight mb-4" style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
            Set up in under 2 minutes
          </h2>
          <p className="text-lg max-w-xl mx-auto" style={{ color: "#94A3B8" }}>
            Three steps. No cloud config, no YAML, no complexity.
          </p>
        </div>

        <div className="grid lg:grid-cols-3 gap-8">
          {STEPS.map((step) => {
            const Icon = step.icon
            return (
              <div key={step.number} className="rounded-xl p-6 relative gradient-border"
                style={{ background: "#0D1B2A" }}>
                <div className="flex items-start gap-4 mb-4">
                  <span className="text-5xl font-bold font-mono leading-none" style={{ color: "rgba(255,255,255,0.45)" }}>
                    {step.number}
                  </span>
                  <div className="mt-1">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-3"
                      style={{ background: "rgba(124,58,237,0.15)", border: "1px solid rgba(124,58,237,0.3)" }}>
                      <Icon size={16} style={{ color: "#A78BFA" }} />
                    </div>
                    <h3 className="text-xl font-semibold mb-2">{step.title}</h3>
                    <p className="text-sm leading-relaxed" style={{ color: "#94A3B8" }}>{step.description}</p>
                  </div>
                </div>
                <pre className="mt-4 p-4 rounded-lg text-xs font-mono leading-6 overflow-x-auto"
                  style={{ background: "#060B14", color: "#00DC82", border: "1px solid rgba(0,220,130,0.15)" }}>
                  {step.code}
                </pre>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
