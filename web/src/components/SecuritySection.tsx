import { ShieldCheck, Github } from "lucide-react"

export default function SecuritySection() {
  return (
    <section className="py-24">
      <div className="max-w-7xl mx-auto px-6">
        <div className="rounded-2xl overflow-hidden" style={{ background: "linear-gradient(135deg, #0D1B2A 0%, #091420 100%)", border: "1px solid rgba(0,220,130,0.15)" }}>
          <div className="grid lg:grid-cols-2 gap-0">
            {/* Left: text */}
            <div className="p-10 lg:p-16">
              <div className="inline-block text-xs font-mono px-3 py-1 rounded-full mb-6"
                style={{ background: "rgba(0,220,130,0.1)", border: "1px solid rgba(0,220,130,0.25)", color: "#00DC82" }}>
                SECURITY ARCHITECTURE
              </div>
              <h2 className="text-4xl font-bold tracking-tight mb-4" style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
                Built like a vault.<br />
                <span style={{ color: "#00DC82" }}>Not a spreadsheet.</span>
              </h2>
              <p className="text-base leading-relaxed mb-8" style={{ color: "#94A3B8" }}>
                Every decision in PushKey&apos;s architecture was made with one question: what happens if someone gets access to the file?
                The answer is: nothing. They still can&apos;t read your keys.
              </p>

              <div className="space-y-4">
                {[
                  { title: "AES-256-GCM encryption", desc: "Authenticated encryption — encrypted AND tamper-evident." },
                  { title: "Argon2id KDF", desc: "200,000 iterations. GPU brute-force is not economically viable." },
                  { title: "Open source crypto layer", desc: "The vault is MIT licensed on GitHub. Read every line that touches your keys before you trust it.", link: "https://github.com/ebothegreat/pushkey" },
                  { title: "chmod 600 vault files", desc: "Vault files are owner-read-only. Other users on the same machine can't read them." },
                ].map(item => (
                  <div key={item.title} className="flex items-start gap-3">
                    <div className="w-1.5 h-1.5 rounded-full mt-2 flex-shrink-0" style={{ background: "#00DC82" }} />
                    <div>
                      <span className="text-sm font-semibold">{item.title}</span>
                      <span className="text-sm" style={{ color: "#94A3B8" }}> — {item.desc}</span>
                      {"link" in item && (
                        <a href={item.link} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 ml-2 text-xs transition-all"
                          style={{ color: "#64748B" }}
                          onMouseEnter={e => { e.currentTarget.style.color = "#94A3B8" }}
                          onMouseLeave={e => { e.currentTarget.style.color = "#64748B" }}>
                          <Github size={10} /> view on GitHub
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right: vault visualization */}
            <div className="p-10 lg:p-16 flex items-center justify-center" style={{ borderLeft: "1px solid rgba(255,255,255,0.06)" }}>
              <div className="w-full max-w-sm">
                <div className="text-center mb-6">
                  <div className="w-20 h-20 rounded-2xl flex items-center justify-center mx-auto mb-4 glow-green"
                    style={{ background: "rgba(0,220,130,0.15)", border: "1px solid rgba(0,220,130,0.4)" }}>
                    <ShieldCheck size={36} style={{ color: "#00DC82" }} />
                  </div>
                  <div className="font-mono text-sm" style={{ color: "#00DC82" }}>vault.enc</div>
                  <div className="text-xs mt-1" style={{ color: "#64748B" }}>~/.pushkey/vault.enc · chmod 600</div>
                </div>

                <div className="space-y-2">
                  {[
                    ["Encryption", "AES-256-GCM"],
                    ["KDF", "Argon2id (200k iter)"],
                    ["Salt", "Unique per installation"],
                    ["Network", "None — local only"],
                    ["Backup", "Auto before every write"],
                    ["Password stored", "Never"],
                  ].map(([label, value]) => (
                    <div key={label} className="flex justify-between items-center py-2.5 px-4 rounded-lg"
                      style={{ background: "rgba(6,11,20,0.6)", border: "1px solid rgba(255,255,255,0.06)" }}>
                      <span className="text-xs font-mono" style={{ color: "#64748B" }}>{label}</span>
                      <span className="text-xs font-mono font-medium" style={{ color: "#00DC82" }}>{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
