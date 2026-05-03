"use client"
import { useState } from "react"
import { Check, Minus, Zap } from "lucide-react"

interface Tier {
  key: string
  name: string
  price: { monthly: number; annual: number } | null
  priceNote?: string
  desc: string
  cta: string
  ctaHref: string
  ctaHrefAnnual?: string  // Optional separate Stripe link for annual billing
  highlight: boolean
  color: string
  badge?: string
  features: (string | null)[]
  extras?: string[]
}

// Stripe Payment Links — paste yours here after creating products in Stripe dashboard
const STRIPE_LINKS = {
  pro: {
    monthly: process.env.NEXT_PUBLIC_STRIPE_PRO_MONTHLY || "/admin/login",
    annual:  process.env.NEXT_PUBLIC_STRIPE_PRO_ANNUAL  || "/admin/login",
  },
  team: {
    monthly: process.env.NEXT_PUBLIC_STRIPE_TEAM_MONTHLY || "/admin/login",
    annual:  process.env.NEXT_PUBLIC_STRIPE_TEAM_ANNUAL  || "/admin/login",
  },
  lifetime: process.env.NEXT_PUBLIC_STRIPE_LIFETIME || "mailto:hello@push-key.com?subject=Lifetime Deal",
}

const TIERS: Tier[] = [
  {
    key: "free",
    name: "Free",
    price: { monthly: 0, annual: 0 },
    desc: "Personal use, side projects",
    cta: "Download Free",
    ctaHref: "https://github.com/Push-Key/pushkey/releases",
    highlight: false,
    color: "#64748B",
    features: [
      "15 API keys",
      "1 project folder",
      "1 device",
      "TOTP MFA",
      "Local encryption",
      null,
      null,
      null,
    ],
  },
  {
    key: "pro",
    name: "Pro",
    price: { monthly: 19, annual: 14 },
    desc: "Power users & indie makers",
    cta: "Go Pro",
    ctaHref: STRIPE_LINKS.pro.monthly,
    ctaHrefAnnual: STRIPE_LINKS.pro.annual,
    highlight: true,
    color: "#7C3AED",
    badge: "Most Popular",
    features: [
      "Unlimited keys",
      "Unlimited projects",
      "3 devices",
      "TOTP MFA",
      "Local encryption",
      "Cloud encrypted backup",
      "Git history scanner",
      "CI/CD sync (GitHub, Vercel, Railway)",
    ],
  },
  {
    key: "team",
    name: "Team",
    price: { monthly: 39, annual: 29 },
    priceNote: "per 5 seats · $10/seat after",
    desc: "Dev teams that ship together",
    cta: "Start Team",
    ctaHref: STRIPE_LINKS.team.monthly,
    ctaHrefAnnual: STRIPE_LINKS.team.annual,
    highlight: false,
    color: "#34D399",
    features: [
      "Unlimited keys",
      "Unlimited projects",
      "5 devices per seat",
      "TOTP MFA",
      "Local + team encryption",
      "Cloud encrypted backup",
      "Git history scanner",
      "CI/CD sync + Team RBAC",
    ],
  },
  {
    key: "lifetime",
    name: "Lifetime",
    price: null,
    priceNote: "one-time · limited to 500",
    desc: "Pay once, own forever",
    cta: "Get Lifetime Deal",
    ctaHref: STRIPE_LINKS.lifetime,
    highlight: false,
    color: "#FBBF24",
    badge: "Limited",
    features: [
      "All Pro features, forever",
      "All future Pro updates",
      "Team LTD at $299 (5 seats)",
      "Priority support",
      null,
      null,
      null,
      null,
    ],
  },
  {
    key: "enterprise",
    name: "Enterprise",
    price: null,
    priceNote: "from $499/mo",
    desc: "Compliance-heavy teams",
    cta: "Contact Sales",
    ctaHref: "mailto:hello@push-key.com",
    highlight: false,
    color: "#F59E0B",
    features: [
      "Unlimited keys & projects",
      "Unlimited devices",
      "TOTP + YubiKey MFA",
      "All encryption modes",
      "Cloud + on-prem backup",
      "Git history scanner",
      "CI/CD sync",
      "RBAC + SSO (SAML/Okta/Azure AD)",
    ],
    extras: ["Dedicated support + SLA", "Custom audit log export"],
  },
]

export default function Pricing() {
  const [annual, setAnnual] = useState(false)

  return (
    <section id="pricing" className="py-24" style={{ background: "rgba(13,27,42,0.2)" }}>
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-12">
          <div className="inline-block text-xs font-mono px-3 py-1 rounded-full mb-4"
            style={{ background: "rgba(124,58,237,0.1)", border: "1px solid rgba(124,58,237,0.25)", color: "#A78BFA" }}>
            PRICING
          </div>
          <h2 className="text-4xl lg:text-5xl font-bold tracking-tight mb-4" style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
            Start free. Scale when you need it.
          </h2>
          <p className="text-lg max-w-lg mx-auto mb-8" style={{ color: "#94A3B8" }}>
            No credit card required to start. Upgrade when your team grows.
          </p>

          {/* Annual toggle */}
          <div className="inline-flex items-center gap-3 p-1 rounded-lg" style={{ background: "#0D1B2A", border: "1px solid rgba(255,255,255,0.08)" }}>
            <button onClick={() => setAnnual(false)}
              className="px-4 py-1.5 rounded-md text-sm font-medium transition-all"
              style={{ background: !annual ? "#1E293B" : "transparent", color: !annual ? "#F8FAFC" : "#64748B" }}>
              Monthly
            </button>
            <button onClick={() => setAnnual(true)}
              className="px-4 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-2"
              style={{ background: annual ? "#1E293B" : "transparent", color: annual ? "#F8FAFC" : "#64748B" }}>
              Annual
              <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: "rgba(0,220,130,0.15)", color: "#00DC82" }}>Save 25%</span>
            </button>
          </div>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {TIERS.map((tier) => (
            <div key={tier.key}
              className="rounded-xl p-5 flex flex-col relative transition-all duration-200"
              style={{
                background: tier.highlight ? "rgba(124,58,237,0.08)" : "#0D1B2A",
                border: tier.highlight ? "1px solid rgba(124,58,237,0.4)" : "1px solid rgba(255,255,255,0.08)",
              }}>
              {tier.badge && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 text-xs font-semibold px-3 py-1 rounded-full"
                  style={{ background: "#7C3AED", color: "#fff" }}>
                  {tier.badge}
                </div>
              )}

              {/* Header */}
              <div className="mb-4">
                <div className="text-xs font-mono mb-1" style={{ color: tier.color }}>{tier.name.toUpperCase()}</div>
                <div className="text-sm mb-3" style={{ color: "#64748B" }}>{tier.desc}</div>
                {tier.price !== null ? (
                  <div>
                    <span className="text-3xl font-bold" style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
                      ${annual ? tier.price.annual : tier.price.monthly}
                    </span>
                    <span className="text-sm ml-1" style={{ color: "#64748B" }}>/mo</span>
                    {tier.priceNote && <div className="text-xs mt-0.5" style={{ color: "#64748B" }}>{tier.priceNote}</div>}
                    {annual && tier.price.monthly > 0 && (
                      <div className="text-xs mt-1" style={{ color: "#00DC82" }}>
                        Save ${(tier.price.monthly - tier.price.annual) * 12}/yr
                      </div>
                    )}
                  </div>
                ) : (
                  <div>
                    <div className="text-2xl font-bold">{tier.key === "lifetime" ? "$149" : "Custom"}</div>
                    {tier.priceNote && <div className="text-xs mt-0.5" style={{ color: "#64748B" }}>{tier.priceNote}</div>}
                  </div>
                )}
              </div>

              {/* CTA */}
              {(() => {
                const href = annual && tier.ctaHrefAnnual ? tier.ctaHrefAnnual : tier.ctaHref
                return (
              <a href={href}
                target={href.startsWith("http") ? "_blank" : undefined}
                rel={href.startsWith("http") ? "noopener noreferrer" : undefined}
                className="block text-center text-sm font-semibold py-2.5 px-4 rounded-lg mb-5 transition-all"
                style={{
                  background: tier.highlight ? "#7C3AED" : "rgba(255,255,255,0.06)",
                  color: tier.highlight ? "#fff" : "#F8FAFC",
                  border: tier.highlight ? "none" : "1px solid rgba(255,255,255,0.1)",
                }}
                onMouseEnter={e => { e.currentTarget.style.opacity = "0.85" }}
                onMouseLeave={e => { e.currentTarget.style.opacity = "1" }}>
                {tier.cta}
              </a>
              )})()}

              {/* Features */}
              <div className="space-y-2 flex-1">
                {tier.features.map((f, i) =>
                  f ? (
                    <div key={i} className="flex items-start gap-2">
                      <Check size={13} className="mt-0.5 flex-shrink-0" style={{ color: tier.color }} />
                      <span className="text-xs leading-relaxed" style={{ color: "#94A3B8" }}>{f}</span>
                    </div>
                  ) : (
                    <div key={i} className="flex items-center gap-2">
                      <Minus size={13} className="flex-shrink-0" style={{ color: "#1E293B" }} />
                      <span className="text-xs" style={{ color: "#1E293B" }}>—</span>
                    </div>
                  )
                )}
                {tier.extras?.map((e, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <Zap size={13} className="mt-0.5 flex-shrink-0" style={{ color: tier.color }} />
                    <span className="text-xs leading-relaxed" style={{ color: "#94A3B8" }}>{e}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Vault Key USB waitlist */}
        <div className="mt-8 max-w-lg mx-auto rounded-xl p-5 flex items-center gap-5" style={{ background: "#0D1B2A", border: "1px solid rgba(99,102,241,0.25)" }}>
          <span className="text-3xl flex-shrink-0">🔌</span>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-mono mb-0.5" style={{ color: "#818CF8" }}>VAULT KEY USB — Coming soon</div>
            <p className="text-xs leading-relaxed" style={{ color: "#64748B" }}>
              Off-grid hardware vault. Encrypted vault lives on the USB — unplug and keys vanish from memory. Includes Pro for 12 months.
            </p>
          </div>
          <a href="mailto:hello@push-key.com?subject=Vault Key USB"
            className="flex-shrink-0 text-xs font-semibold py-2 px-4 rounded-lg transition-all whitespace-nowrap"
            style={{ background: "rgba(99,102,241,0.12)", color: "#818CF8", border: "1px solid rgba(99,102,241,0.25)" }}
            onMouseEnter={e => { e.currentTarget.style.opacity = "0.8" }}
            onMouseLeave={e => { e.currentTarget.style.opacity = "1" }}>
            Join Waitlist
          </a>
        </div>

        {/* Footnote */}
        <p className="text-center text-xs mt-8" style={{ color: "#64748B" }}>
          All plans include local-first encryption. No keys are stored in our cloud — ever. Enterprise audit logs are end-to-end encrypted.
        </p>
      </div>
    </section>
  )
}
