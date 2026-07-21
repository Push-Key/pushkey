"use client"
import { useState, type FormEvent } from "react"
import { useRouter } from "next/navigation"
import Image from "next/image"
import { Lock } from "lucide-react"
import { adminApi } from "@/lib/admin-api"

export default function AdminLogin() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [mfaCode, setMfaCode] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError("")
    setLoading(true)
    try {
      await adminApi.login({ email, password, mfa_code: mfaCode })
      router.replace("/admin/licenses")
    } catch {
      setError("Invalid admin credentials")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#060B14] flex items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-3 mb-8">
          <Image
            src="/pushkey-logo.png"
            alt="Pushkey"
            width={44}
            height={44}
          />
          <div>
            <p className="text-base font-bold tracking-wide text-white leading-none">PUSHKEY</p>
            <p className="text-[9px] text-[#94A3B8] tracking-widest uppercase">Admin Console</p>
          </div>
        </div>

        <form
          onSubmit={submit}
          className="bg-[#0D1B2A] border border-white/8 rounded-xl p-6 space-y-4"
        >
          <div>
            <p className="text-sm font-semibold text-white mb-1">Admin Account</p>
            <p className="text-xs text-[#94A3B8] mb-4">Sign in with an assigned admin account.</p>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="admin@example.com"
              className="w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/50 outline-none focus:border-[#00DC82]/50 transition-colors mb-3"
            />
            <div className="relative">
              <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="Password"
                className="w-full bg-[#112233] border border-white/8 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/50 outline-none focus:border-[#00DC82]/50 transition-colors"
              />
            </div>
            <input
              inputMode="numeric"
              value={mfaCode}
              onChange={e => setMfaCode(e.target.value)}
              placeholder="MFA code"
              className="w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/50 outline-none focus:border-[#00DC82]/50 transition-colors mt-3"
            />
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={loading || !email || !password}
            className="w-full bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2.5 rounded-lg hover:bg-[#00DC82]/90 disabled:opacity-40 transition-colors"
          >
            {loading ? "Verifying…" : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  )
}
