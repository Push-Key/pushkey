"use client"
import { useState } from "react"
import { ChevronDown } from "lucide-react"

const FAQS = [
  {
    q: "Is PushKey really local-only? No cloud at all?",
    a: "Correct. By default, PushKey stores everything in ~/.pushkey/ on your machine with chmod 600 permissions. Starter+ plans add an optional encrypted cloud backup — but it's opt-in, and your keys are encrypted before leaving your device. We never see plaintext secrets.",
  },
  {
    q: "What happens if I forget my master password?",
    a: "The vault cannot be decrypted without your master password — by design. We recommend setting up a secure password backup (a password manager, printed and stored safely). There is no reset flow, because a reset flow would mean we have a way in.",
  },
  {
    q: "How is this different from HashiCorp Vault or AWS Secrets Manager?",
    a: "Those are network-first server-side solutions with significant operational overhead. PushKey is local-first, opinionated, and built for individual devs and small teams. Setup is 2 minutes, not 2 days. It complements, not replaces, server-side secret stores.",
  },
  {
    q: "Can I use PushKey on Linux / macOS / Windows?",
    a: "Yes. PushKey is a Python application with a desktop GUI (customtkinter). It runs on macOS, Windows, and Linux. Pre-built executables are available for Windows. Mac and Linux users run it via Python.",
  },
  {
    q: "What providers are supported for auto-detection and rotation links?",
    a: "PushKey auto-detects 25+ providers including OpenAI, Anthropic, Stripe, AWS, Vercel, Supabase, GitHub, GitLab, Alpaca, OANDA, Coinbase, Twilio, Sendgrid, and more. Any key not matching a known provider still works — it just won't have a direct dashboard link.",
  },
  {
    q: "How does CI/CD sync work?",
    a: "Pro+ plans can push secrets directly to GitHub Actions secrets, Vercel environment variables, and Railway variables from inside PushKey. You authorize the integrations once, then manage secrets in one place instead of separate dashboards for each CI provider.",
  },
  {
    q: "Is the source code available?",
    a: "Yes — PushKey is open source (MIT license). The encryption, key derivation, and vault logic are all auditable. You don't have to trust our claims — you can read the code.",
  },
  {
    q: "What is the Vault Key USB?",
    a: "The Vault Key USB is a physical hardware product for users who want a fully off-grid setup. Your encrypted vault lives exclusively on the USB drive — nothing is stored on your machine. Plug it in to access your keys, unplug and they vanish from memory entirely. It ships pre-imaged with Pushkey and includes a 12-month Pro license. Ideal for security researchers, journalists, or anyone handling high-value production secrets.",
  },
  {
    q: "Is there a lifetime deal option?",
    a: "Yes — we offer a limited lifetime deal for Pro ($149 one-time) and Team ($299 one-time for 5 seats). Both include all future updates for that tier. Lifetime licenses are capped at 500 units to ensure we can sustainably support them. Once they're gone, they're gone.",
  },
]

export default function FAQ() {
  const [open, setOpen] = useState<number | null>(null)

  return (
    <section id="faq" className="py-24" style={{ background: "rgba(13,27,42,0.2)" }}>
      <div className="max-w-3xl mx-auto px-6">
        <div className="text-center mb-16">
          <div className="inline-block text-xs font-mono px-3 py-1 rounded-full mb-4"
            style={{ background: "rgba(124,58,237,0.1)", border: "1px solid rgba(124,58,237,0.25)", color: "#A78BFA" }}>
            FAQ
          </div>
          <h2 className="text-4xl font-bold tracking-tight" style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
            Questions we get a lot
          </h2>
        </div>

        <div className="space-y-2">
          {FAQS.map((faq, i) => (
            <div key={i} className="rounded-xl overflow-hidden"
              style={{ background: "#0D1B2A", border: "1px solid rgba(255,255,255,0.08)" }}>
              <button
                className="w-full flex items-center justify-between p-5 text-left"
                onClick={() => setOpen(open === i ? null : i)}>
                <span className="text-sm font-semibold pr-4">{faq.q}</span>
                <ChevronDown size={16} className="flex-shrink-0 transition-transform" style={{
                  color: "#64748B",
                  transform: open === i ? "rotate(180deg)" : "rotate(0deg)"
                }} />
              </button>
              {open === i && (
                <div className="px-5 pb-5">
                  <p className="text-sm leading-relaxed" style={{ color: "#94A3B8" }}>{faq.a}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
