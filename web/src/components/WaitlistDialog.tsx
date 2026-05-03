"use client"
import { useEffect, useState } from "react"
import { X, Check, Loader2 } from "lucide-react"

interface Props {
  open: boolean
  onClose: () => void
  source?: string  // e.g. "vault-key-usb" — tracks where the signup came from
  title?: string
  subtitle?: string
}

export default function WaitlistDialog({
  open,
  onClose,
  source = "general",
  title = "Join the waitlist",
  subtitle = "We'll email you the moment it's ready. No spam, no marketing fluff."
}: Props) {
  const [email, setEmail] = useState("")
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [error, setError] = useState<string>("")

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [open, onClose])

  // Reset state when dialog reopens
  useEffect(() => {
    if (open) {
      setStatus("idle")
      setError("")
    }
  }, [open])

  if (!open) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email || !email.includes("@")) {
      setError("Please enter a valid email")
      return
    }
    setStatus("loading")
    setError("")
    try {
      const res = await fetch("/api/waitlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, source })
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error || "Could not save your email")
      setStatus("success")
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Something went wrong"
      setError(message)
      setStatus("error")
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(6,11,20,0.85)", backdropFilter: "blur(4px)" }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        className="rounded-2xl max-w-md w-full p-8 relative"
        style={{ background: "#0D1B2A", border: "1px solid rgba(124,58,237,0.3)", boxShadow: "0 20px 60px rgba(0,0,0,0.5)" }}
      >
        <button
          onClick={onClose}
          aria-label="Close"
          className="absolute top-4 right-4 p-1 rounded-md transition-colors"
          style={{ color: "#64748B" }}
          onMouseEnter={e => { e.currentTarget.style.color = "#F8FAFC" }}
          onMouseLeave={e => { e.currentTarget.style.color = "#64748B" }}
        >
          <X size={20} />
        </button>

        {status === "success" ? (
          <div className="text-center py-4">
            <div
              className="inline-flex items-center justify-center w-14 h-14 rounded-full mb-4"
              style={{ background: "rgba(0,220,130,0.15)" }}
            >
              <Check size={28} style={{ color: "#00DC82" }} />
            </div>
            <h3 className="text-2xl font-bold mb-2" style={{ color: "#F8FAFC" }}>You&apos;re on the list</h3>
            <p className="text-sm" style={{ color: "#94A3B8" }}>
              We&apos;ll email <strong style={{ color: "#F8FAFC" }}>{email}</strong> the moment it&apos;s ready.
            </p>
            <button
              onClick={onClose}
              className="mt-6 text-sm px-5 py-2 rounded-lg font-medium"
              style={{ background: "rgba(255,255,255,0.06)", color: "#F8FAFC", border: "1px solid rgba(255,255,255,0.1)" }}
            >
              Close
            </button>
          </div>
        ) : (
          <>
            <h3 className="text-2xl font-bold mb-2" style={{ color: "#F8FAFC" }}>{title}</h3>
            <p className="text-sm mb-6" style={{ color: "#94A3B8" }}>{subtitle}</p>

            <form onSubmit={handleSubmit}>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                disabled={status === "loading"}
                autoFocus
                required
                className="w-full px-4 py-3 rounded-lg text-sm mb-3 focus:outline-none transition-all"
                style={{
                  background: "#060B14",
                  color: "#F8FAFC",
                  border: error ? "1px solid #F87171" : "1px solid rgba(255,255,255,0.1)"
                }}
                onFocus={e => { if (!error) e.currentTarget.style.borderColor = "#7C3AED" }}
                onBlur={e => { if (!error) e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)" }}
              />
              {error && (
                <p className="text-xs mb-3" style={{ color: "#F87171" }}>{error}</p>
              )}
              <button
                type="submit"
                disabled={status === "loading"}
                className="w-full py-3 rounded-lg font-semibold text-sm flex items-center justify-center gap-2 transition-all"
                style={{
                  background: "#7C3AED",
                  color: "#fff",
                  opacity: status === "loading" ? 0.7 : 1,
                  cursor: status === "loading" ? "wait" : "pointer"
                }}
              >
                {status === "loading" ? (
                  <><Loader2 size={16} className="animate-spin" /> Joining...</>
                ) : (
                  "Notify me"
                )}
              </button>
              <p className="text-xs text-center mt-4" style={{ color: "#64748B" }}>
                One-click unsubscribe. No marketing email lists.
              </p>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
