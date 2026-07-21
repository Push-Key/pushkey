"use client";

import { useEffect, useState } from "react";
import {
  Copy, Check, Loader2, Plus, Trash2, AlertTriangle, ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { api, type AgentToken } from "@/lib/api";
import { toast } from "@/lib/toast";

// ── helpers ───────────────────────────────────────────────────────────────────

const SCOPES = ["read", "write", "admin"] as const;
type Scope = typeof SCOPES[number];

const scopeColor: Record<Scope, string> = {
  read:  "text-emerald-400 border-emerald-400/30 bg-emerald-400/5",
  write: "text-orange-400 border-orange-400/30 bg-orange-400/5",
  admin: "text-red-400 border-red-400/30 bg-red-400/5",
};

function ErrorBanner({ msg }: { msg: string }) {
  return (
    <div className="rounded-md border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/10 p-3 text-sm text-red-400">
      {msg}
    </div>
  );
}

function ScopeBadge({ scope }: { scope: string }) {
  const cls = scopeColor[scope as Scope] ?? "text-[var(--color-muted-foreground)] border-[var(--color-card)] bg-[var(--color-card)]";
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-mono ${cls}`}>
      {scope}
    </span>
  );
}

// ── one-time token reveal ─────────────────────────────────────────────────────

function TokenReveal({ token }: { token: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(token);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="rounded-lg border border-cyan-400/30 bg-cyan-400/5 p-4 space-y-3">
      <div className="flex items-center gap-2 text-orange-400">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <p className="text-sm font-semibold">Save this token — shown once</p>
      </div>
      <p className="text-xs text-[var(--color-muted-foreground)]">
        This value will not be displayed again. Copy it now and store it securely.
      </p>
      <div className="flex items-center gap-2">
        <code className="flex-1 rounded bg-[var(--color-card)] border border-[var(--color-card)] px-3 py-2 text-xs font-mono text-cyan-400 break-all select-all">
          {token}
        </code>
        <Button
          size="icon"
          variant="outline"
          onClick={copy}
          className="shrink-0 border-cyan-400/30 hover:bg-cyan-400/10"
          title="Copy token"
        >
          {copied
            ? <Check className="h-4 w-4 text-emerald-400" />
            : <Copy className="h-4 w-4 text-cyan-400" />}
        </Button>
      </div>
    </div>
  );
}

// ── create agent form ─────────────────────────────────────────────────────────

function CreateAgentForm({
  onCreated,
}: {
  onCreated: (agent: AgentToken) => void;
}) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<Set<Scope>>(new Set(["read"]));
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [newToken, setNewToken] = useState<string | null>(null);

  const toggleScope = (s: Scope) => {
    setScopes((prev) => {
      const next = new Set(prev);
      next.has(s) ? next.delete(s) : next.add(s);
      return next;
    });
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || scopes.size === 0) return;
    setLoading(true);
    setErr(null);
    setNewToken(null);
    try {
      const r = await api.createAgent(name.trim(), Array.from(scopes));
      setNewToken(r.token);
      onCreated({ id: r.id, name: r.name, scopes: r.scopes });
      setName("");
      setScopes(new Set(["read"]));
      toast.success("Agent token created");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "create failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-lg border border-[var(--color-card)] bg-[var(--color-card)] p-4 space-y-4">
      <p className="text-sm font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-cyan-400" />
        Create agent token
      </p>

      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3 items-end">
          <div className="space-y-1">
            <Label htmlFor="agent-name" className="text-xs">Agent name</Label>
            <Input
              id="agent-name"
              placeholder="deploy-bot"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="text-sm"
              required
            />
          </div>
          <Button
            type="submit"
            disabled={loading || !name.trim() || scopes.size === 0}
            className="bg-cyan-400/10 border border-cyan-400/30 text-cyan-400 hover:bg-cyan-400/20"
          >
            {loading
              ? <Loader2 className="h-4 w-4 animate-spin mr-1" />
              : <Plus className="h-4 w-4 mr-1" />}
            Create
          </Button>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">Scopes</Label>
          <div className="flex gap-3">
            {SCOPES.map((s) => (
              <label key={s} className="flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={scopes.has(s)}
                  onChange={() => toggleScope(s)}
                  className="accent-cyan-400"
                />
                <ScopeBadge scope={s} />
              </label>
            ))}
          </div>
        </div>

        {err && <ErrorBanner msg={err} />}
      </form>

      {newToken && <TokenReveal token={newToken} />}
    </div>
  );
}

// ── agent row ─────────────────────────────────────────────────────────────────

function AgentRow({
  agent,
  onRevoke,
}: {
  agent: AgentToken;
  onRevoke: (id: string) => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleRevoke = async () => {
    if (!confirm) { setConfirm(true); return; }
    setRevoking(true);
    setErr(null);
    try {
      await api.revokeAgent(agent.id);
      onRevoke(agent.id);
      toast.success("Token revoked");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "revoke failed");
      setRevoking(false);
      setConfirm(false);
    }
  };

  return (
    <>
      <TableRow>
        <TableCell className="font-mono text-sm">{agent.name}</TableCell>
        <TableCell>
          <div className="flex flex-wrap gap-1">
            {agent.scopes.map((s) => (
              <ScopeBadge key={s} scope={s} />
            ))}
          </div>
        </TableCell>
        <TableCell className="text-xs text-[var(--color-muted-foreground)]">
          {agent.created ? new Date(agent.created).toLocaleDateString() : "—"}
        </TableCell>
        <TableCell className="text-right">
          {confirm ? (
            <div className="flex items-center justify-end gap-1">
              <Button
                size="sm"
                variant="destructive"
                onClick={handleRevoke}
                disabled={revoking}
                className="h-7 text-xs"
              >
                {revoking ? <Loader2 className="h-3 w-3 animate-spin" /> : "Confirm revoke"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setConfirm(false)}
                className="h-7 text-xs"
              >
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              onClick={handleRevoke}
              className="h-7 hover:text-red-400"
            >
              <Trash2 className="h-3.5 w-3.5 mr-1" />
              Revoke
            </Button>
          )}
        </TableCell>
      </TableRow>
      {err && (
        <TableRow>
          <TableCell colSpan={4} className="pt-0 pb-2">
            <ErrorBanner msg={err} />
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

// ── main export ───────────────────────────────────────────────────────────────

export function AgentsTab() {
  const [agents, setAgents] = useState<AgentToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setErr(null);
    try {
      const r = await api.listAgents();
      setAgents(r.tokens);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const handleCreated = (agent: AgentToken) =>
    setAgents((prev) => [agent, ...prev]);

  const handleRevoke = (id: string) =>
    setAgents((prev) => prev.filter((a) => a.id !== id));

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Agents</h1>
        <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
          {loading ? "Loading…" : "Refresh"}
        </Button>
      </div>

      {err && <ErrorBanner msg={err} />}

      {/* Create form */}
      <CreateAgentForm onCreated={handleCreated} />

      {/* Agents table */}
      <div className="rounded-md border bg-[var(--color-card)]">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Scopes</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {!loading && agents.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="py-8 text-center text-sm text-[var(--color-muted-foreground)]"
                >
                  No agent tokens. Create one above.
                </TableCell>
              </TableRow>
            ) : (
              agents.map((a) => (
                <AgentRow key={a.id} agent={a} onRevoke={handleRevoke} />
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
