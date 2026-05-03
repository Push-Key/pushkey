"use client"
import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react"
import { adminApi, type AdminStats } from "@/lib/admin-api"

interface AdminCtx {
  secret: string
  stats: AdminStats | null
  refreshStats: () => void
}

const Ctx = createContext<AdminCtx>({ secret: "", stats: null, refreshStats: () => {} })

export function useAdmin() {
  return useContext(Ctx)
}

export function AdminProvider({ secret, children }: { secret: string; children: ReactNode }) {
  const [stats, setStats] = useState<AdminStats | null>(null)

  const refreshStats = useCallback(() => {
    if (!secret) return
    adminApi.stats(secret).then(setStats).catch(() => {})
  }, [secret])

  useEffect(() => { refreshStats() }, [refreshStats])

  return <Ctx.Provider value={{ secret, stats, refreshStats }}>{children}</Ctx.Provider>
}
