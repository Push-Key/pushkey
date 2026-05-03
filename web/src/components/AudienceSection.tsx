const PROVIDERS = [
  "OpenAI", "Anthropic", "Stripe", "Supabase", "Twilio",
  "Vercel", "Railway", "AWS", "GitHub", "OANDA",
  "Replicate", "Pinecone", "Resend", "Cloudflare", "Notion",
]

export default function AudienceSection() {
  return (
    <section className="py-16" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
      <div className="max-w-7xl mx-auto px-6">
        <div className="max-w-3xl mx-auto text-center mb-10">
          <div
            className="inline-block text-xs font-mono px-3 py-1 rounded-full mb-4"
            style={{
              background: "rgba(124,58,237,0.1)",
              border: "1px solid rgba(124,58,237,0.25)",
              color: "#A78BFA",
            }}
          >
            BUILT FOR AI BUILDERS &amp; DEVELOPERS
          </div>
          <p className="text-lg leading-relaxed" style={{ color: "#94A3B8" }}>
            Managing too many API keys across too many projects?{" "}
            <span style={{ color: "#F8FAFC" }}>
              PushKey is a local-first API key vault that stores secrets encrypted on your machine,
              tracks rotation health, detects providers automatically, and writes the right{" "}
              <code
                className="font-mono text-sm px-1.5 py-0.5 rounded"
                style={{ background: "rgba(255,255,255,0.08)", color: "#F8FAFC" }}
              >
                .env
              </code>{" "}
              files into the right projects.
            </span>{" "}
            No copy-paste. No secrets in plain text.
          </p>
        </div>

        {/* Provider pill list */}
        <div className="flex flex-wrap justify-center gap-2">
          {PROVIDERS.map((p) => (
            <span
              key={p}
              className="text-xs font-mono px-3 py-1.5 rounded-full"
              style={{
                background: "rgba(255,255,255,0.04)",
                border: "1px solid rgba(255,255,255,0.08)",
                color: "#64748B",
              }}
            >
              {p}
            </span>
          ))}
          <span
            className="text-xs font-mono px-3 py-1.5 rounded-full"
            style={{
              background: "rgba(0,220,130,0.06)",
              border: "1px solid rgba(0,220,130,0.15)",
              color: "#00DC82",
            }}
          >
            + 20 more
          </span>
        </div>
      </div>
    </section>
  )
}
