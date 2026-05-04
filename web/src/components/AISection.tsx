"use client"
import { useState } from "react"
import { Bot, Terminal, Zap, ShieldCheck, Sparkles, Globe, ChevronRight } from "lucide-react"

const TOOLS = [
  { cmd: "unlock_vault(\"••••••••\")",     desc: "Unlock once per session" },
  { cmd: "list_keys()",                    desc: "See all your keys" },
  { cmd: "get_key(\"OPENAI_API_KEY\")",    desc: "Retrieve a value" },
  { cmd: "inject_env(\"/my-app\")",        desc: "Populate .env instantly" },
  { cmd: "check_health()",                 desc: "Flag stale keys" },
  { cmd: "rotate_key(\"STRIPE_KEY\", …)", desc: "Rotate + timestamp" },
]

const DISCOVERY_STEPS = [
  { label: "GET /llms.txt",              desc: "Read product + tool docs" },
  { label: "GET /.well-known/mcp.json", desc: "Fetch transport config" },
  { label: "spawn pushkey_mcp.py",       desc: "Connect MCP server" },
  { label: "unlock_vault(pw)",           desc: "Open the vault" },
]

const CLIENT_TABS = ["Claude Code", "OpenAI Agents SDK", "Any MCP client"] as const
type ClientTab = typeof CLIENT_TABS[number]

const CLIENT_CODE: Record<ClientTab, string> = {
  "Claude Code": `# ~/.claude/claude_desktop_config.json
{
  "mcpServers": {
    "pushkey": {
      "command": "python",
      "args": ["/path/to/pushkey_mcp.py"]
    }
  }
}`,
  "OpenAI Agents SDK": `from agents import Agent, MCPServerStdio

pushkey = MCPServerStdio(
    command="python",
    args=["/path/to/pushkey_mcp.py"]
)

agent = Agent(
    name="DevAgent",
    mcp_servers=[pushkey]
)`,
  "Any MCP client": `# 1. Fetch the manifest
GET https://pushkey.dev/.well-known/mcp.json

# 2. Spawn the stdio server
python /path/to/pushkey_mcp.py

# 3. Or connect via SSE
python pushkey_mcp.py --port 8765
# → http://localhost:8765/sse`,
}

const STEPS = [
  {
    icon: Bot,
    title: "Agent queries the vault",
    desc: "After connecting, the agent calls list_keys to see what's available — filtered by project, env, or provider.",
    code: `> What API keys do I have for this project?

Agent: Calling list_keys(project="/my-app")…

  OPENAI_API_KEY   OpenAI   prod   ✓ fresh
  STRIPE_KEY       Stripe   prod   ⚠ 87 days old`,
  },
  {
    icon: Zap,
    title: "Agent sets up .env for you",
    desc: "Agent pulls the right keys from your vault and writes the .env — without values ever appearing in the conversation.",
    code: `> Set up the .env for my new Next.js app

Agent: Calling inject_env("/projects/my-app",
  keys=["OPENAI_API_KEY", "STRIPE_KEY"])

✓ .env written  ✓ .gitignore updated`,
  },
]

export default function AISection() {
  const [activeTab, setActiveTab] = useState<ClientTab>("Claude Code")

  return (
    <section id="ai-integration" className="py-24" style={{ background: "rgba(10,18,35,0.6)" }}>
      <div className="max-w-7xl mx-auto px-6">

        {/* Header */}
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 text-xs font-mono px-3 py-1 rounded-full mb-4"
            style={{ background: "rgba(167,139,250,0.1)", border: "1px solid rgba(167,139,250,0.25)", color: "#A78BFA" }}>
            <Bot size={12} />
            MCP SERVER · AGENT READY
          </div>
          <h2 className="text-4xl lg:text-5xl font-bold tracking-tight mb-4"
            style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
            Built for AI agents<br />
            <span style={{ color: "#A78BFA" }}>and the humans who send them</span>
          </h2>
          <p className="text-lg max-w-2xl mx-auto" style={{ color: "#94A3B8" }}>
            Pushkey ships a built-in MCP server compatible with Claude Code, OpenAI Agents SDK, VS Code Copilot,
            and any MCP client. Agents can discover, connect, and operate the vault autonomously.
          </p>
        </div>

        {/* Agent discovery flow */}
        <div className="rounded-xl p-6 mb-8"
          style={{ background: "#0D1B2A", border: "1px solid rgba(0,220,130,0.15)" }}>
          <div className="flex items-center gap-2 mb-5">
            <Globe size={14} style={{ color: "#00DC82" }} />
            <p className="text-xs font-mono font-semibold" style={{ color: "#00DC82" }}>HOW AN AGENT DISCOVERS AND CONNECTS</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {DISCOVERY_STEPS.map((step, i) => (
              <div key={i} className="flex items-center gap-2">
                <div className="rounded-lg px-3 py-2 text-center"
                  style={{ background: "#060B14", border: "1px solid rgba(0,220,130,0.12)" }}>
                  <p className="text-xs font-mono mb-0.5" style={{ color: "#00DC82" }}>{step.label}</p>
                  <p className="text-xs" style={{ color: "#475569" }}>{step.desc}</p>
                </div>
                {i < DISCOVERY_STEPS.length - 1 && (
                  <ChevronRight size={14} style={{ color: "#1E3A2F" }} />
                )}
              </div>
            ))}
            <a href="/llms.txt" target="_blank" rel="noopener noreferrer"
              className="ml-auto text-xs font-mono px-3 py-1.5 rounded-lg hidden sm:block"
              style={{ background: "rgba(0,220,130,0.07)", color: "#00DC82", border: "1px solid rgba(0,220,130,0.15)" }}>
              llms.txt ↗
            </a>
          </div>
        </div>

        {/* Connect + workflow row */}
        <div className="grid lg:grid-cols-2 gap-6 mb-8">

          {/* Client config with tabs */}
          <div className="rounded-xl p-6"
            style={{ background: "#0D1B2A", border: "1px solid rgba(167,139,250,0.12)" }}>
            <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-4"
              style={{ background: "rgba(167,139,250,0.12)", border: "1px solid rgba(167,139,250,0.25)" }}>
              <Terminal size={16} style={{ color: "#A78BFA" }} />
            </div>
            <h3 className="font-semibold text-base mb-1">Connect your agent</h3>
            <p className="text-sm leading-relaxed mb-4" style={{ color: "#94A3B8" }}>
              One config block wires Pushkey into any MCP-compatible agent framework.
            </p>

            {/* Tabs */}
            <div className="flex gap-1 mb-3 p-1 rounded-lg"
              style={{ background: "#060B14", border: "1px solid rgba(255,255,255,0.04)" }}>
              {CLIENT_TABS.map(tab => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className="flex-1 text-xs font-mono py-1.5 px-2 rounded-md transition-all"
                  style={{
                    background: activeTab === tab ? "rgba(167,139,250,0.15)" : "transparent",
                    color: activeTab === tab ? "#A78BFA" : "#475569",
                    border: activeTab === tab ? "1px solid rgba(167,139,250,0.25)" : "1px solid transparent",
                  }}>
                  {tab}
                </button>
              ))}
            </div>

            <pre className="p-4 rounded-lg text-xs font-mono leading-6 overflow-x-auto whitespace-pre-wrap"
              style={{ background: "#060B14", color: "#00DC82", border: "1px solid rgba(0,220,130,0.12)" }}>
              {CLIENT_CODE[activeTab]}
            </pre>
          </div>

          {/* Steps stacked */}
          <div className="flex flex-col gap-4">
            {STEPS.map((step, i) => {
              const Icon = step.icon
              return (
                <div key={i} className="rounded-xl p-5 flex-1"
                  style={{ background: "#0D1B2A", border: "1px solid rgba(167,139,250,0.12)" }}>
                  <div className="flex items-start gap-3 mb-3">
                    <div className="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
                      style={{ background: "rgba(167,139,250,0.12)", border: "1px solid rgba(167,139,250,0.2)" }}>
                      <Icon size={13} style={{ color: "#A78BFA" }} />
                    </div>
                    <div>
                      <h3 className="font-semibold text-sm mb-0.5">{step.title}</h3>
                      <p className="text-xs leading-relaxed" style={{ color: "#94A3B8" }}>{step.desc}</p>
                    </div>
                  </div>
                  <pre className="p-3 rounded-lg text-xs font-mono leading-5 overflow-x-auto whitespace-pre-wrap"
                    style={{ background: "#060B14", color: "#00DC82", border: "1px solid rgba(0,220,130,0.12)" }}>
                    {step.code}
                  </pre>
                </div>
              )
            })}
          </div>
        </div>

        {/* Tool grid */}
        <div className="rounded-2xl p-8"
          style={{ background: "#0D1B2A", border: "1px solid rgba(167,139,250,0.15)" }}>
          <div className="flex items-center gap-3 mb-6">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ background: "rgba(167,139,250,0.12)", border: "1px solid rgba(167,139,250,0.25)" }}>
              <ShieldCheck size={15} style={{ color: "#A78BFA" }} />
            </div>
            <div>
              <p className="font-semibold text-sm">9 MCP tools — available to any connected agent</p>
              <p className="text-xs" style={{ color: "#64748B" }}>Keys never appear in conversation history — agents call tools silently</p>
            </div>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {TOOLS.map(({ cmd, desc }) => (
              <div key={cmd} className="rounded-lg px-4 py-3 flex items-center gap-3"
                style={{ background: "#060B14", border: "1px solid rgba(255,255,255,0.05)" }}>
                <code className="text-xs font-mono flex-1 truncate" style={{ color: "#A78BFA" }}>{cmd}</code>
                <span className="text-xs shrink-0" style={{ color: "#475569" }}>{desc}</span>
              </div>
            ))}
          </div>

          <div className="mt-6 pt-6 flex flex-wrap gap-6 items-center"
            style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ background: "#00DC82" }} />
              <span className="text-xs" style={{ color: "#94A3B8" }}>Claude Code (stdio)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ background: "#A78BFA" }} />
              <span className="text-xs" style={{ color: "#94A3B8" }}>OpenAI Agents SDK (stdio)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ background: "#60A5FA" }} />
              <span className="text-xs" style={{ color: "#94A3B8" }}>VS Code Copilot (SSE)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ background: "#F59E0B" }} />
              <span className="text-xs" style={{ color: "#94A3B8" }}>Zero-knowledge — server never sees plaintext</span>
            </div>
          </div>
        </div>

        {/* Skill callout */}
        <div className="mt-6 rounded-xl px-6 py-5 flex items-start gap-4"
          style={{ background: "#0D1B2A", border: "1px solid rgba(167,139,250,0.2)" }}>
          <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
            style={{ background: "rgba(167,139,250,0.12)", border: "1px solid rgba(167,139,250,0.25)" }}>
            <Sparkles size={15} style={{ color: "#A78BFA" }} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <p className="font-semibold text-sm">Claude Code Skill — auto-activates</p>
              <span className="text-xs px-2 py-0.5 rounded-full font-mono"
                style={{ background: "rgba(0,220,130,0.1)", color: "#00DC82", border: "1px solid rgba(0,220,130,0.2)" }}>
                included
              </span>
            </div>
            <p className="text-sm mb-3" style={{ color: "#94A3B8" }}>
              A companion skill ships with Pushkey and teaches Claude exactly when and how to call the vault tools.
              Mention any of these phrases and Claude routes the request automatically.
            </p>
            <div className="flex flex-wrap gap-2">
              {["API keys", ".env files", "secrets", "credentials", "rotate key", "set up env for X", "what keys do I have"].map(t => (
                <span key={t} className="text-xs font-mono px-2 py-0.5 rounded"
                  style={{ background: "rgba(167,139,250,0.07)", color: "#A78BFA", border: "1px solid rgba(167,139,250,0.15)" }}>
                  &ldquo;{t}&rdquo;
                </span>
              ))}
            </div>
          </div>
          <a href="/llms.txt" target="_blank" rel="noopener noreferrer"
            className="shrink-0 text-xs font-mono px-3 py-1.5 rounded-lg transition-colors hidden sm:block"
            style={{ background: "rgba(167,139,250,0.1)", color: "#A78BFA", border: "1px solid rgba(167,139,250,0.2)" }}>
            llms.txt ↗
          </a>
        </div>

      </div>
    </section>
  )
}
