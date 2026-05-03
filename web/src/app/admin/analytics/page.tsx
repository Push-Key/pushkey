"use client"
import { useEffect, useState } from "react"
import { BarChart2, TrendingUp, Key, Shield, Activity } from "lucide-react"
import { adminApi, type License, type AdminStats } from "@/lib/admin-api"
import { useAdmin } from "../_context"

const TIER_COLORS: Record<string, string> = {
  free: "#38BDF8",
  starter: "#A78BFA",
  pro: "#C084FC",
  team: "#34D399",
  enterprise: "#F59E0B",
}

function StatCard({ icon, label, value, sub, color }: {
  icon: React.ReactNode; label: string; value: string | number; sub: string; color: string
}) {
  return (
    <div className="bg-[#0D1B2A] border border-white/8 rounded-xl p-5 flex items-start gap-4">
      <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" style={{ background: color + "20" }}>
        <span style={{ color }}>{icon}</span>
      </div>
      <div>
        <p className="text-[10px] uppercase tracking-widest text-[#94A3B8]">{label}</p>
        <p className="text-2xl font-bold text-white mt-0.5">{value}</p>
        <p className="text-xs text-[#94A3B8] mt-0.5">{sub}</p>
      </div>
    </div>
  )
}

// Simple bar chart using divs
function BarChart({ data, colorFn }: { data: { label: string; value: number; color?: string }[]; colorFn?: (l: string) => string }) {
  const max = Math.max(...data.map(d => d.value), 1)
  return (
    <div className="flex items-end gap-3 h-32 pt-4">
      {data.map(d => (
        <div key={d.label} className="flex-1 flex flex-col items-center gap-1.5">
          <span className="text-xs text-[#94A3B8]">{d.value}</span>
          <div className="w-full rounded-t" style={{ height: `${Math.max(4, (d.value / max) * 80)}px`, background: d.color ?? (colorFn ? colorFn(d.label) : "#00DC82") }} />
          <span className="text-[10px] text-[#94A3B8] capitalize truncate w-full text-center">{d.label}</span>
        </div>
      ))}
    </div>
  )
}

// Donut chart using SVG
function DonutChart({ slices, size = 120 }: {
  slices: { label: string; value: number; color: string }[]
  size?: number
}) {
  const total = slices.reduce((s, x) => s + x.value, 0) || 1
  const r = size / 2 - 12
  const cx = size / 2
  const cy = size / 2
  let angle = -Math.PI / 2
  const paths = slices.map(s => {
    const sweep = (s.value / total) * 2 * Math.PI
    const x1 = cx + r * Math.cos(angle)
    const y1 = cy + r * Math.sin(angle)
    angle += sweep
    const x2 = cx + r * Math.cos(angle)
    const y2 = cy + r * Math.sin(angle)
    const large = sweep > Math.PI ? 1 : 0
    return { ...s, d: `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z` }
  })
  return (
    <svg width={size} height={size} className="shrink-0">
      <circle cx={cx} cy={cy} r={r - 16} fill="#060B14" />
      {paths.map((p, i) => (
        <path key={i} d={p.d} fill={p.color} opacity={0.85} />
      ))}
    </svg>
  )
}

export default function AnalyticsPage() {
  const { secret } = useAdmin()
  const [licenses, setLicenses] = useState<License[]>([])
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!secret) return
    Promise.all([adminApi.licenses(secret), adminApi.stats(secret)])
      .then(([lics, s]) => { setLicenses(lics); setStats(s) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [secret])

  // Compute tier distribution
  const tierCounts = licenses.reduce<Record<string, number>>((acc, l) => {
    acc[l.tier] = (acc[l.tier] ?? 0) + 1
    return acc
  }, {})

  // Platform distribution
  const platformCounts = licenses.reduce<Record<string, number>>((acc, l) => {
    const p = l.platform?.toLowerCase().includes("mac") ? "macOS"
      : l.platform?.toLowerCase().includes("linux") ? "Linux"
      : l.platform ? "Windows" : "Unknown"
    acc[p] = (acc[p] ?? 0) + 1
    return acc
  }, {})

  // Status donut
  const statusSlices = [
    { label: "Active",  value: stats?.total_active ?? 0,  color: "#34D399" },
    { label: "Expired", value: licenses.filter(l => l.status === "expired").length, color: "#F59E0B" },
    { label: "Revoked", value: stats?.revoked ?? 0, color: "#F87171" },
  ].filter(s => s.value > 0)

  const tierBarData = Object.entries(tierCounts).map(([k, v]) => ({
    label: k, value: v, color: TIER_COLORS[k] ?? "#64748B",
  }))

  const platformBarData = Object.entries(platformCounts).map(([k, v]) => ({
    label: k, value: v,
  }))

  const total = licenses.length
  const rotationRate = total > 0
    ? Math.round((licenses.filter(l => l.status !== "active").length / total) * 100)
    : 0

  if (loading) return <div className="p-8 text-[#94A3B8]">Loading analytics…</div>

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-xl font-bold text-white">Analytics</h1>
        <p className="text-sm text-[#94A3B8] mt-1">License health, tier distribution, and platform breakdown</p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <StatCard icon={<Key size={18} />} label="Total Keys" value={total} sub="All time" color="#00DC82" />
        <StatCard icon={<TrendingUp size={18} />} label="New This Week" value={stats?.week_delta ?? 0} sub="Activations" color="#38BDF8" />
        <StatCard icon={<Shield size={18} />} label="Pro + Team" value={stats?.pro_team ?? 0} sub={`${total ? Math.round(((stats?.pro_team ?? 0) / total) * 100) : 0}% paid`} color="#A78BFA" />
        <StatCard icon={<Activity size={18} />} label="Churn Rate" value={`${rotationRate}%`} sub="Expired or revoked" color="#F59E0B" />
      </div>

      <div className="grid grid-cols-3 gap-6 mb-6">
        {/* Tier distribution */}
        <div className="col-span-2 bg-[#0D1B2A] border border-white/8 rounded-xl p-5">
          <p className="text-sm font-semibold text-white mb-1">Tier Distribution</p>
          <p className="text-xs text-[#94A3B8] mb-4">Keys by plan tier</p>
          {tierBarData.length > 0
            ? <BarChart data={tierBarData} />
            : <p className="text-center text-[#94A3B8] py-10 text-sm">No data yet — generate some keys first</p>
          }
        </div>

        {/* Status donut */}
        <div className="bg-[#0D1B2A] border border-white/8 rounded-xl p-5">
          <p className="text-sm font-semibold text-white mb-1">Key Status</p>
          <p className="text-xs text-[#94A3B8] mb-4">Active vs expired vs revoked</p>
          <div className="flex flex-col items-center gap-4">
            {statusSlices.length > 0
              ? <>
                  <DonutChart slices={statusSlices} size={140} />
                  <div className="space-y-2 w-full">
                    {statusSlices.map(s => (
                      <div key={s.label} className="flex items-center justify-between text-xs">
                        <span className="flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full inline-block" style={{ background: s.color }} />
                          <span className="text-[#94A3B8]">{s.label}</span>
                        </span>
                        <span className="text-white font-medium">{s.value}</span>
                      </div>
                    ))}
                  </div>
                </>
              : <p className="text-center text-[#94A3B8] py-10 text-sm">No data</p>
            }
          </div>
        </div>
      </div>

      {/* Platform breakdown */}
      <div className="bg-[#0D1B2A] border border-white/8 rounded-xl p-5">
        <p className="text-sm font-semibold text-white mb-1">Platform Breakdown</p>
        <p className="text-xs text-[#94A3B8] mb-4">Where clients are running Pushkey</p>
        {platformBarData.length > 0
          ? <BarChart data={platformBarData} colorFn={() => "#60A5FA"} />
          : <p className="text-center text-[#94A3B8] py-10 text-sm">No platform data — platform is populated when a client first heartbeats</p>
        }
      </div>
    </div>
  )
}
