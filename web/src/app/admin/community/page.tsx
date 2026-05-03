"use client"
import { MessageCircle, Star, GitBranch, Share2, ArrowRight, ThumbsUp } from "lucide-react"
import { useState } from "react"

const ROADMAP = [
  { phase: "v1.1", title: "GitHub App integration", desc: "Webhook-triggered PR scans, automatic secret detection alerts.", status: "in_progress", votes: 42 },
  { phase: "v1.2", title: "Slack & Discord alerts", desc: "Push rotation reminders and expiry warnings to your team channels.", status: "planned", votes: 38 },
  { phase: "v1.2", title: "SSO / SAML login", desc: "Enterprise single sign-on via Okta, Azure AD, Google Workspace.", status: "planned", votes: 29 },
  { phase: "v1.3", title: "Audit log export", desc: "Export full audit trail as CSV or stream to S3/Datadog.", status: "planned", votes: 24 },
  { phase: "v1.3", title: "Dynamic secrets (TTL keys)", desc: "Auto-rotating keys with configurable TTL — no more manual rotation.", status: "planned", votes: 51 },
  { phase: "v2.0", title: "Self-hosted registry", desc: "Host your own provider registry instead of pulling from GitHub.", status: "idea", votes: 17 },
]

const CHANGELOG = [
  { version: "v1.0.3", date: "2026-05-03", items: ["Admin console — license dashboard with full CRUD", "GitHub Hub skeleton — repo connect + scan status", "Analytics page with tier/platform/status charts"] },
  { version: "v1.0.2", date: "2026-04-28", items: ["CLI: 8 commands including push, pull, rotate, inject", "Provider detection for 32+ API key formats", "V2 vault format with Argon2id KDF"] },
  { version: "v1.0.1", date: "2026-04-20", items: ["Theme switching — dark/light, in-place recolor", "Lazy tab rendering + idle pre-render", "Resize debouncer for canvas frames"] },
  { version: "v1.0.0", date: "2026-04-10", items: ["Initial release — AES-256-GCM vault", "Dashboard, All Keys, Projects, Security, Cloud, Timeline", "License tier system with heartbeat"] },
]

const STATUS_CFG = {
  in_progress: { label: "In Progress", color: "text-sky-400",     bg: "bg-sky-900/30 border-sky-800/50" },
  planned:     { label: "Planned",     color: "text-violet-400",  bg: "bg-violet-900/30 border-violet-800/50" },
  idea:        { label: "Idea",        color: "text-[#94A3B8]",   bg: "bg-white/5 border-white/10" },
}

export default function CommunityPage() {
  const [votes, setVotes] = useState<Record<string, number>>({})

  function vote(title: string, base: number) {
    setVotes(v => ({ ...v, [title]: v[title] !== undefined ? undefined as unknown as number : base + 1 }))
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-xl font-bold text-white">Community</h1>
        <p className="text-sm text-[#94A3B8] mt-1">Join the conversation, vote on features, follow the roadmap</p>
      </div>

      {/* Community links */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        {[
          { icon: <MessageCircle size={20} />, title: "Discord", desc: "Chat with other Pushkey users and the dev team", color: "#5865F2", href: "#" },
          { icon: <GitBranch size={20} />, title: "GitHub", desc: "Source, issues, and pull requests", color: "#94A3B8", href: "#" },
          { icon: <Share2 size={20} />, title: "Twitter / X", desc: "Announcements and release notes", color: "#1D9BF0", href: "#" },
        ].map(link => (
          <a
            key={link.title}
            href={link.href}
            className="bg-[#0D1B2A] border border-white/8 rounded-xl p-5 flex items-start gap-4 hover:border-white/20 transition-colors group"
          >
            <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" style={{ background: link.color + "20", color: link.color }}>
              {link.icon}
            </div>
            <div className="flex-1">
              <p className="text-sm font-semibold text-white">{link.title}</p>
              <p className="text-xs text-[#94A3B8] mt-0.5">{link.desc}</p>
            </div>
            <ArrowRight size={14} className="text-[#94A3B8] group-hover:text-white transition-colors mt-0.5 shrink-0" />
          </a>
        ))}
      </div>

      <div className="grid grid-cols-5 gap-6">
        {/* Roadmap */}
        <div className="col-span-3">
          <div className="bg-[#0D1B2A] border border-white/8 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-white/8 flex items-center justify-between">
              <p className="font-semibold text-white">Roadmap</p>
              <p className="text-xs text-[#94A3B8]">Vote for features you want</p>
            </div>
            <div className="divide-y divide-white/5">
              {ROADMAP.map(item => {
                const s = STATUS_CFG[item.status as keyof typeof STATUS_CFG]
                const hasVoted = votes[item.title] !== undefined
                const displayVotes = hasVoted ? votes[item.title] : item.votes
                return (
                  <div key={item.title} className="flex items-center gap-4 px-5 py-4 hover:bg-white/[0.02] transition-colors">
                    <button
                      onClick={() => vote(item.title, item.votes)}
                      className={`flex flex-col items-center gap-0.5 shrink-0 w-10 transition-colors ${hasVoted ? "text-[#00DC82]" : "text-[#94A3B8] hover:text-white"}`}
                    >
                      <ThumbsUp size={14} />
                      <span className="text-[10px] font-semibold">{displayVotes}</span>
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-[10px] text-[#94A3B8] font-mono">{item.phase}</span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${s.bg} ${s.color}`}>{s.label}</span>
                      </div>
                      <p className="text-sm font-medium text-white">{item.title}</p>
                      <p className="text-xs text-[#94A3B8] mt-0.5">{item.desc}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* Changelog */}
        <div className="col-span-2">
          <div className="bg-[#0D1B2A] border border-white/8 rounded-xl overflow-hidden">
            <div className="px-5 py-4 border-b border-white/8 flex items-center gap-2">
              <Star size={14} className="text-[#94A3B8]" />
              <p className="font-semibold text-white">Changelog</p>
            </div>
            <div className="divide-y divide-white/5">
              {CHANGELOG.map(entry => (
                <div key={entry.version} className="px-5 py-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-semibold text-[#00DC82] font-mono">{entry.version}</span>
                    <span className="text-xs text-[#94A3B8]">{entry.date}</span>
                  </div>
                  <ul className="space-y-1">
                    {entry.items.map(item => (
                      <li key={item} className="text-xs text-[#94A3B8] flex items-start gap-2">
                        <span className="text-[#00DC82]/60 mt-0.5 shrink-0">•</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
