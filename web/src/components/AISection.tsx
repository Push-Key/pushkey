"use client"
import { Bot, Terminal, Zap, ShieldCheck } from "lucide-react"

const TOOLS = [
  { cmd: "unlock_vault(\"••••••••\")",     desc: "Unlock once per session" },
  { cmd: "list_keys()",                    desc: "See all your keys" },
  { cmd: "get_key(\"OPENAI_API_KEY\")",    desc: "Retrieve a value" },
  { cmd: "inject_env(\"/my-app\")",        desc: "Populate .env instantly" },
  { cmd: "check_health()",                 desc: "Flag stale keys" },
  { cmd: "rotate_key(\"STRIPE_KEY\", …)", desc: "Rotate + timestamp" },
]

const STEPS = [
  {
    icon: Terminal,
    title: "Install the MCP server",
    desc: "One line in your Claude Code config wires Pushkey's vault directly into the AI.",
    code: `# ~/.claude/claude_desktop_config.json\n{\n  "mcpServers": {\n    "pushkey": {\n      "command": "python",\n      "args": ["/path/to/pushkey_mcp.py"]\n    }\n  }\n}`,
  },
  {
    icon: Bot,
    title: "Claude Code gains vault access",
    desc: "Restart Claude Code. Nine tools appear in the AI's toolbox — unlock, list, get, add, inject, health, rotate, and more.",
    code: `> What API keys do I have for this project?\n\nClaude: Calling list_keys(project="/my-app")…\n\n  OPENAI_API_KEY   OpenAI   prod   ✓ fresh\n  STRIPE_KEY       Stripe   prod   ⚠ 87 days old`,
  },
  {
    icon: Zap,
    title: "AI sets up .env for you",
    desc: "Ask Claude to wire up a new project and it pulls the right keys from your vault and writes the .env — without ever showing values in chat.",
    code: `> Set up the .env for my new Next.js app\n\nClaude: Calling inject_env("/projects/my-app",\n  keys=["OPENAI_API_KEY", "STRIPE_KEY"])\n\n✓ .env written  ✓ .gitignore updated`,
  },
]

export default function AISection() {
  return (
    <section id="ai-integration" className="py-24" style={{ background: "rgba(10,18,35,0.6)" }}>
      <div className="max-w-7xl mx-auto px-6">

        {/* Header */}
        <div className="text-center mb-16">
          <div className="inline-flex items-center gap-2 text-xs font-mono px-3 py-1 rounded-full mb-4"
            style={{ background: "rgba(167,139,250,0.1)", border: "1px solid rgba(167,139,250,0.25)", color: "#A78BFA" }}>
            <Bot size={12} />
            CLAUDE CODE · MCP SERVER
          </div>
          <h2 className="text-4xl lg:text-5xl font-bold tracking-tight mb-4"
            style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>
            Your AI coding assistant<br />
            <span style={{ color: "#A78BFA" }}>knows your keys</span>
          </h2>
          <p className="text-lg max-w-2xl mx-auto" style={{ color: "#94A3B8" }}>
            Pushkey ships a built-in MCP server for Claude Code and VS Code Copilot.
            Your AI can unlock the vault, retrieve keys, populate <code className="font-mono text-sm px-1 rounded"
              style={{ background: "rgba(255,255,255,0.06)", color: "#00DC82" }}>.env</code> files,
            and flag stale secrets — all without you leaving the editor.
          </p>
        </div>

        {/* Steps */}
        <div className="grid lg:grid-cols-3 gap-6 mb-16">
          {STEPS.map((step, i) => {
            const Icon = step.icon
            return (
              <div key={i} className="rounded-xl p-6"
                style={{ background: "#0D1B2A", border: "1px solid rgba(167,139,250,0.12)" }}>
                <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-4"
                  style={{ background: "rgba(167,139,250,0.12)", border: "1px solid rgba(167,139,250,0.25)" }}>
                  <Icon size={16} style={{ color: "#A78BFA" }} />
                </div>
                <h3 className="font-semibold text-base mb-2">{step.title}</h3>
                <p className="text-sm leading-relaxed mb-4" style={{ color: "#94A3B8" }}>{step.desc}</p>
                <pre className="p-4 rounded-lg text-xs font-mono leading-6 overflow-x-auto whitespace-pre-wrap"
                  style={{ background: "#060B14", color: "#00DC82", border: "1px solid rgba(0,220,130,0.12)" }}>
                  {step.code}
                </pre>
              </div>
            )
          })}
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
              <p className="font-semibold text-sm">9 MCP tools available to Claude Code</p>
              <p className="text-xs" style={{ color: "#64748B" }}>Keys never appear in conversation history — the AI calls tools silently</p>
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
              <span className="text-xs" style={{ color: "#94A3B8" }}>Works with Claude Code (stdio)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ background: "#A78BFA" }} />
              <span className="text-xs" style={{ color: "#94A3B8" }}>Works with VS Code Copilot (SSE)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ background: "#F59E0B" }} />
              <span className="text-xs" style={{ color: "#94A3B8" }}>Zero-knowledge — server never sees plaintext</span>
            </div>
          </div>
        </div>

      </div>
    </section>
  )
}
