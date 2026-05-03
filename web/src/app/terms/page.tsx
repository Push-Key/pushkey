export const metadata = { title: "Terms of Service — PushKey" }

export default function TermsPage() {
  return (
    <main style={{ background: "#060B14", color: "#F8FAFC", minHeight: "100vh" }}>
      <div className="max-w-3xl mx-auto px-6 py-24">
        <a href="/" className="text-sm" style={{ color: "#94A3B8" }}>← Back to PushKey</a>
        <h1 className="text-4xl font-bold mt-6 mb-4">Terms of Service</h1>
        <p className="text-sm mb-8" style={{ color: "#64748B" }}>Last updated: May 3, 2026</p>

        <div className="space-y-6 leading-relaxed" style={{ color: "#CBD5E1" }}>
          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>The agreement</h2>
            <p>By using PushKey, you agree to these terms. PushKey is a software tool we provide &quot;as is&quot; — you&apos;re responsible for your own data, backups, and recovery codes.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>Your responsibility</h2>
            <ul className="list-disc pl-6 space-y-2">
              <li><strong>Master password:</strong> We cannot recover it. If you lose it, your vault is unrecoverable unless you saved your recovery code.</li>
              <li><strong>Recovery code:</strong> Treat it like a seed phrase. Store offline. We do not retain copies.</li>
              <li><strong>Cloud sync (Pro+):</strong> We store ciphertext only. We can&apos;t restore data we can&apos;t decrypt.</li>
              <li><strong>License keys:</strong> Don&apos;t share them. Each license is tied to your account.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>Subscriptions &amp; refunds</h2>
            <p>Monthly and annual subscriptions auto-renew until canceled. You can cancel anytime — access continues through your paid period. We offer a 14-day refund on first-time annual purchases. Lifetime purchases are non-refundable after 14 days.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>Acceptable use</h2>
            <p>Don&apos;t use PushKey to store credentials for systems you don&apos;t own or have authorization to access. Don&apos;t reverse-engineer the proprietary cloud backend. Don&apos;t resell or sublicense.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>Limitation of liability</h2>
            <p>PushKey is provided without warranty. We&apos;re not liable for lost data, lost passwords, lost recovery codes, breach of accounts you stored credentials for, or business losses arising from use of the software. Maximum liability is capped at amounts paid in the prior 12 months.</p>
          </section>

          <section>
            <h2 className="text-xl font-semibold mb-3" style={{ color: "#F8FAFC" }}>Contact</h2>
            <p>Questions: <a href="mailto:hello@push-key.com" style={{ color: "#00D9FF" }}>hello@push-key.com</a></p>
          </section>
        </div>
      </div>
    </main>
  )
}
