"use client"
import { useEffect, useState, type ReactNode } from "react"
import { useRouter, usePathname } from "next/navigation"
import Link from "next/link"
import Image from "next/image"
import {
  LayoutGrid, XCircle, KeyRound, BarChart2, GitBranch, Headphones, Users,
  Settings as SettingsIcon, FileText, ShieldCheck,
} from "lucide-react"
import { AdminProvider, useAdmin } from "./_context"

function Sidebar() {
  const { stats } = useAdmin()
  const pathname = usePathname()

  const navItem = (
    href: string,
    icon: ReactNode,
    label: string,
    badge?: number,
    badgeColor = "bg-sky-500/20 text-sky-400",
  ) => {
    const active = pathname === href || pathname.startsWith(href + "/")
    return (
      <Link
        href={href}
        className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
          active
            ? "bg-white/8 text-white"
            : "text-[#94A3B8] hover:text-white hover:bg-white/5"
        }`}
      >
        <span className={active ? "text-[#00DC82]" : ""}>{icon}</span>
        <span className="flex-1">{label}</span>
        {badge !== undefined && (
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${badgeColor}`}>
            {badge}
          </span>
        )}
      </Link>
    )
  }

  return (
    <aside className="w-[220px] shrink-0 bg-[#0D1B2A] border-r border-white/8 flex flex-col h-screen sticky top-0">
      {/* Logo */}
      <div className="px-5 pt-5 pb-4 border-b border-white/8">
        <div className="flex items-center gap-3">
          <Image
            src="/pushkey-logo.png"
            alt="Pushkey"
            width={72}
            height={72}
            className="shrink-0"
          />
          <div>
            <p className="text-sm font-bold tracking-wide text-white leading-none">PUSHKEY</p>
            <p className="text-[9px] text-[#94A3B8] tracking-widest uppercase mt-0.5">Admin Console</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <p className="text-[9px] tracking-widest uppercase text-[#94A3B8]/50 px-3 pb-2">Operations</p>
        {navItem("/admin/licenses", <LayoutGrid size={15} />, "Licenses", stats?.total_active)}
        {navItem("/admin/contacts", <Users size={15} />, "Contacts")}
        {navItem(
          "/admin/revoked",
          <XCircle size={15} />,
          "Revoked",
          stats?.revoked,
          "bg-red-500/20 text-red-400",
        )}
        {navItem("/admin/generate", <KeyRound size={15} />, "Generate Key")}

        <div className="pt-4">
          <p className="text-[9px] tracking-widest uppercase text-[#94A3B8]/50 px-3 pb-2">Tools</p>
          {navItem("/admin/analytics", <BarChart2 size={15} />, "Analytics")}
          {navItem("/admin/audit", <ShieldCheck size={15} />, "Audit Log")}
          {navItem("/admin/github", <GitBranch size={15} />, "GitHub Hub")}
          {navItem("/admin/support", <Headphones size={15} />, "Support")}
          {navItem("/admin/community", <Users size={15} />, "Community")}
        </div>

        <div className="pt-4">
          <p className="text-[9px] tracking-widest uppercase text-[#94A3B8]/50 px-3 pb-2">System</p>
          {navItem("/admin/settings", <SettingsIcon size={15} />, "Settings")}
          {navItem("/admin/docs", <FileText size={15} />, "API Docs")}
        </div>
      </nav>
    </aside>
  )
}

function Shell({ secret, children }: { secret: string; children: ReactNode }) {
  return (
    <AdminProvider secret={secret}>
      <div className="flex min-h-screen bg-[#060B14] text-white">
        <Sidebar />
        <main className="flex-1 min-w-0">{children}</main>
      </div>
    </AdminProvider>
  )
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [secret, setSecret] = useState<string | null>(null)

  useEffect(() => {
    const s = sessionStorage.getItem("pk_admin_secret")
    if (!s && pathname !== "/admin/login") {
      router.replace("/admin/login")
    } else {
      setSecret(s ?? "")
    }
  }, [pathname, router])

  if (secret === null) return null
  if (pathname === "/admin/login") return <>{children}</>
  return <Shell secret={secret}>{children}</Shell>
}
