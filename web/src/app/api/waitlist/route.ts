import { NextResponse } from "next/server"

export const runtime = "edge"

interface WaitlistRequest {
  email: string
  source?: string
}

export async function POST(req: Request) {
  let body: WaitlistRequest
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 })
  }

  const { email, source = "general" } = body

  // Basic validation
  if (!email || typeof email !== "string" || !email.includes("@") || email.length > 320) {
    return NextResponse.json({ error: "Invalid email" }, { status: 400 })
  }

  const cleanEmail = email.trim().toLowerCase()
  const cleanSource = String(source).slice(0, 64)
  const ts = new Date().toISOString()

  // Try Supabase REST insert if configured
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

  if (supabaseUrl && supabaseKey) {
    try {
      const res = await fetch(`${supabaseUrl}/rest/v1/waitlist`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "apikey": supabaseKey,
          "Authorization": `Bearer ${supabaseKey}`,
          "Prefer": "resolution=merge-duplicates,return=minimal"
        },
        body: JSON.stringify({ email: cleanEmail, source: cleanSource, created_at: ts })
      })
      if (res.ok || res.status === 409) {
        // 409 = duplicate (unique constraint), still treat as success
        return NextResponse.json({ ok: true })
      }
      // Don't leak details — log server-side, return generic
      const text = await res.text().catch(() => "")
      console.error("[waitlist] Supabase error:", res.status, text)
    } catch (err) {
      console.error("[waitlist] Supabase fetch failed:", err)
    }
  }

  // Fallback: log to Vercel logs so signups aren't lost
  console.log(`[waitlist] ${cleanSource}: ${cleanEmail} at ${ts}`)
  return NextResponse.json({ ok: true })
}
