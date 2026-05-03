import { Quote } from "lucide-react"

// TODO: Replace with real customer quotes before publishing.
// These are illustrative placeholders — do not treat as real testimonials.
const TESTIMONIALS = [
  {
    quote: "We had a Stripe key committed to GitHub three years ago. It took a breach notice to catch it. PushKey's git scanner found two more in legacy repos in under 30 seconds.",
    name: "Marcus T.",
    role: "Lead Backend Engineer",
    company: "FinTech startup, 12-person team",
    avatar: "MT",
    color: "#00DC82",
  },
  {
    quote: "The .env injection is the killer feature. I rotate my OpenAI key, and all five of my project folders update before I've even switched windows. This is what dev tooling should feel like.",
    name: "Priya K.",
    role: "Indie Maker",
    company: "Solo founder, 7 SaaS products",
    avatar: "PK",
    color: "#A78BFA",
  },
  {
    quote: "We're a 4-person team. PushKey Team means everyone has access to the shared keys they need without us keeping a Notion doc with secrets in it. That doc was a lawsuit waiting to happen.",
    name: "James R.",
    role: "CTO",
    company: "B2B SaaS, seed-stage",
    avatar: "JR",
    color: "#60A5FA",
  },
  {
    quote: "No cloud. No signup. No trust-me-bro. The vault file is on my machine, encrypted, and PushKey has never sent a single packet I didn't initiate. I audited the source.",
    name: "Aleksei V.",
    role: "Security Engineer",
    company: "Open source contributor",
    avatar: "AV",
    color: "#F59E0B",
  },
]

export default function Testimonials() {
  return (
    <section className="py-24">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <div className="inline-block text-xs font-mono px-3 py-1 rounded-full mb-4"
            style={{ background: "rgba(0,220,130,0.1)", border: "1px solid rgba(0,220,130,0.25)", color: "#00DC82" }}>
            TRUSTED BY ENGINEERS
          </div>
          <h2 className="text-4xl font-bold tracking-tight" style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
            From the people who actually use it
          </h2>
        </div>

        <div className="grid sm:grid-cols-2 gap-6">
          {TESTIMONIALS.map((t) => (
            <div key={t.name} className="rounded-xl p-6"
              style={{ background: "#0D1B2A", border: "1px solid rgba(255,255,255,0.08)" }}>
              <Quote size={20} className="mb-4" style={{ color: t.color, opacity: 0.6 }} />
              <p className="text-sm leading-relaxed mb-6" style={{ color: "#CBD5E1" }}>&ldquo;{t.quote}&rdquo;</p>
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: `${t.color}20`, color: t.color, border: `1px solid ${t.color}30` }}>
                  {t.avatar}
                </div>
                <div>
                  <div className="text-sm font-semibold">{t.name}</div>
                  <div className="text-xs" style={{ color: "#64748B" }}>{t.role} · {t.company}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
