export const metadata = { title: "Privacy Policy — PushKey" }

export default function PrivacyPage() {
  return (
    <main style={{ background: "#060B14", color: "#F8FAFC", minHeight: "100vh" }}>
      <div className="max-w-3xl mx-auto px-6 py-24">
        <a href="/" className="text-sm" style={{ color: "#94A3B8" }}>← Back to PushKey</a>
        <h1 className="text-4xl font-bold mt-6 mb-4">Privacy Policy</h1>
        <p className="text-sm mb-8" style={{ color: "#64748B" }}>Last updated: May 3, 2026</p>

        <div className="space-y-6 leading-relaxed" style={{ color: "#CBD5E1" }}>
          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>The short version</h2>
            <p>PushKey is a local-first encrypted vault. Your master password and unencrypted secrets <strong>never leave your device</strong>. The only data we receive is what you explicitly send us — an email if you sign up for cloud sync, billing info via Stripe, and encrypted ciphertext blobs if you opt into cloud backup.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>What we collect</h2>
            <ul className="list-disc pl-6 space-y-2">
              <li><strong>Account email</strong> — for billing and license delivery</li>
              <li><strong>Stripe customer ID + payment metadata</strong> — handled by Stripe; we never see your card number</li>
              <li><strong>Encrypted vault blob</strong> (Pro+ only, opt-in) — AES-256-GCM ciphertext only; we cannot decrypt it</li>
              <li><strong>License heartbeat</strong> — anonymized device count and tier check, every 24h</li>
              <li><strong>Anonymous usage analytics</strong> — page views on push-key.com only; no personal data</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>What we don&apos;t collect</h2>
            <ul className="list-disc pl-6 space-y-2">
              <li>Your master password (we have no way to recover it)</li>
              <li>The plaintext content of any API key in your vault</li>
              <li>Your salt or any key derivation material</li>
              <li>Telemetry from the desktop app or CLI by default</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>Data deletion</h2>
            <p>Email <a href="mailto:privacy@push-key.com" style={{ color: "#00D9FF" }}>privacy@push-key.com</a> to request deletion of your account and any cloud-synced encrypted blobs. We&apos;ll process within 30 days.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>Contact</h2>
            <p>Questions: <a href="mailto:privacy@push-key.com" style={{ color: "#00D9FF" }}>privacy@push-key.com</a></p>
          </section>
        </div>
      </div>
    </main>
  )
}
