"use client"
import { useState } from "react"
import { GitBranch, Plus, AlertTriangle, CheckCircle, Clock, Trash2, ExternalLink } from "lucide-react"

interface Repo {
  id: string
  url: string
  name: string
  addedAt: string
  status: "clean" | "warning" | "scanning"
  findings: number
  lastScan: string
}

const DEMO_REPOS: Repo[] = []

const STATUS_CFG = {
  clean:    { icon: <CheckCircle size={15} />, text: "text-emerald-400", label: "Clean",    bg: "bg-emerald-900/30 border-emerald-800/50" },
  warning:  { icon: <AlertTriangle size={15} />, text: "text-amber-400",  label: "Issues",   bg: "bg-amber-900/30 border-amber-800/50" },
  scanning: { icon: <Clock size={15} />,        text: "text-sky-400",    label: "Scanning", bg: "bg-sky-900/30 border-sky-800/50" },
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const hrs = Math.floor(diff / 3600000)
  if (hrs < 1) return "< 1 hour ago"
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function GithubHubPage() {
  const [repos, setRepos] = useState<Repo[]>(DEMO_REPOS)
  const [showAdd, setShowAdd] = useState(false)
  const [newUrl, setNewUrl] = useState("")
  const [adding, setAdding] = useState(false)

  function addRepo() {
    if (!newUrl.trim()) return
    setAdding(true)
    setTimeout(() => {
      const name = newUrl.replace("https://github.com/", "").replace(/\/$/, "")
      setRepos(r => [...r, {
        id: Date.now().toString(),
        url: newUrl,
        name,
        addedAt: new Date().toISOString().slice(0, 10),
        status: "scanning",
        findings: 0,
        lastScan: new Date().toISOString(),
      }])
      setNewUrl("")
      setShowAdd(false)
      setAdding(false)
    }, 800)
  }

  function removeRepo(id: string) {
    setRepos(r => r.filter(x => x.id !== id))
  }

  const warnings = repos.filter(r => r.status === "warning")
  const totalFindings = repos.reduce((s, r) => s + r.findings, 0)

  return (
    <div className="p-8">
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-xl font-bold text-white">GitHub Hub</h1>
          <p className="text-sm text-[#94A3B8] mt-1">Monitor repos for leaked API keys and hardcoded secrets</p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 bg-[#00DC82] text-[#060B14] font-semibold text-sm px-4 py-2 rounded-lg hover:bg-[#00DC82]/90 transition-colors"
        >
          <Plus size={14} /> Connect Repo
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <div className="bg-[#0D1B2A] border border-white/8 rounded-xl p-5">
          <p className="text-[10px] uppercase tracking-widest text-[#94A3B8] mb-2">Monitored Repos</p>
          <p className="text-3xl font-bold text-white">{repos.length}</p>
        </div>
        <div className="bg-[#0D1B2A] border border-amber-800/40 rounded-xl p-5">
          <p className="text-[10px] uppercase tracking-widest text-[#94A3B8] mb-2">Repos with Issues</p>
          <p className="text-3xl font-bold text-amber-400">{warnings.length}</p>
        </div>
        <div className="bg-[#0D1B2A] border border-red-800/40 rounded-xl p-5">
          <p className="text-[10px] uppercase tracking-widest text-[#94A3B8] mb-2">Total Findings</p>
          <p className="text-3xl font-bold text-red-400">{totalFindings}</p>
        </div>
      </div>

      {/* Add repo modal */}
      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-[#0D1B2A] border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <p className="font-semibold text-white mb-4">Connect GitHub Repository</p>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-[#94A3B8] uppercase tracking-wider">Repository URL</label>
                <input
                  value={newUrl}
                  onChange={e => setNewUrl(e.target.value)}
                  placeholder="https://github.com/owner/repo"
                  className="mt-1 w-full bg-[#112233] border border-white/8 rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-[#94A3B8]/40 outline-none focus:border-[#00DC82]/50 transition-colors"
                  onKeyDown={e => e.key === "Enter" && addRepo()}
                />
              </div>
              <p className="text-xs text-[#94A3B8]">Pushkey will scan commit history and PR diffs for exposed secrets matching your vault providers.</p>
              <div className="flex gap-3 pt-1">
                <button onClick={() => setShowAdd(false)} className="flex-1 border border-white/10 text-[#94A3B8] text-sm py-2.5 rounded-lg hover:border-white/20 hover:text-white transition-colors">Cancel</button>
                <button onClick={addRepo} disabled={adding || !newUrl.trim()} className="flex-1 bg-[#00DC82] text-[#060B14] font-semibold text-sm py-2.5 rounded-lg hover:bg-[#00DC82]/90 disabled:opacity-40 transition-colors">
                  {adding ? "Connecting…" : "Connect"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Repo list */}
      <div className="bg-[#0D1B2A] border border-white/8 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-white/8">
          <p className="font-semibold text-white">Connected Repositories</p>
        </div>
        {repos.length === 0 ? (
          <div className="px-5 py-16 text-center">
            <GitBranch size={32} className="mx-auto mb-3 text-[#94A3B8]/30" />
            <p className="text-[#94A3B8] text-sm">No repos connected yet</p>
            <p className="text-[#94A3B8]/60 text-xs mt-1">Connect a GitHub repo to start scanning for leaked keys</p>
          </div>
        ) : (
          <div className="divide-y divide-white/5">
            {repos.map(repo => {
              const s = STATUS_CFG[repo.status]
              return (
                <div key={repo.id} className="flex items-center gap-4 px-5 py-4 hover:bg-white/[0.02] transition-colors">
                  <div className="w-9 h-9 rounded-lg bg-white/5 flex items-center justify-center shrink-0">
                    <GitBranch size={16} className="text-[#94A3B8]" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">{repo.name}</p>
                    <p className="text-xs text-[#94A3B8]">Added {repo.addedAt} · Last scan {timeAgo(repo.lastScan)}</p>
                  </div>
                  {repo.status === "warning" && (
                    <div className="text-xs text-amber-300 bg-amber-900/30 border border-amber-800/50 px-2.5 py-1 rounded-full">
                      {repo.findings} finding{repo.findings !== 1 ? "s" : ""}
                    </div>
                  )}
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border ${s.bg} ${s.text}`}>
                    {s.icon} {s.label}
                  </span>
                  <a href={repo.url} target="_blank" rel="noreferrer" className="text-[#94A3B8] hover:text-white transition-colors">
                    <ExternalLink size={14} />
                  </a>
                  <button onClick={() => removeRepo(repo.id)} className="text-[#94A3B8] hover:text-red-400 transition-colors">
                    <Trash2 size={14} />
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Info banner */}
      <div className="mt-6 bg-sky-900/20 border border-sky-800/40 rounded-xl p-4">
        <p className="text-sm font-medium text-sky-300 mb-1">How scanning works</p>
        <p className="text-xs text-sky-300/70 leading-relaxed">
          Pushkey scans your repo&apos;s commit history and open PRs for patterns matching your registered provider keys (OpenAI, Stripe, AWS, etc.).
          Findings show the commit SHA and file path so you can rotate and clean up immediately.
          Full GitHub App integration — including webhook-triggered PR scans — coming soon.
        </p>
      </div>
    </div>
  )
}
