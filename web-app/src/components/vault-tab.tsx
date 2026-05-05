"use client";

import { useEffect, useState, useMemo } from "react";
import { Eye, EyeOff, Search, Copy, Check } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type KeySummary } from "@/lib/api";

const envVariant = (env: string) => {
  if (env === "prod")    return "destructive" as const;
  if (env === "staging") return "warning" as const;
  if (env === "dev")     return "success" as const;
  return "secondary" as const;
};

export function VaultTab() {
  const [keys, setKeys] = useState<KeySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setErr(null);
    try {
      const r = await api.listKeys();
      setKeys(r.keys);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const filtered = useMemo(() => {
    const f = filter.toLowerCase();
    return keys.filter(
      (k) => !f || k.name.toLowerCase().includes(f) || (k.provider ?? "").toLowerCase().includes(f)
    );
  }, [keys, filter]);

  const reveal = async (name: string) => {
    if (revealed[name]) {
      setRevealed((p) => { const n = { ...p }; delete n[name]; return n; });
      return;
    }
    try {
      const detail = await api.revealKey(name);
      setRevealed((p) => ({ ...p, [name]: detail.value }));
      // Auto-clear after 30s
      setTimeout(() => {
        setRevealed((p) => { const n = { ...p }; delete n[name]; return n; });
      }, 30_000);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "reveal failed");
    }
  };

  const copy = async (name: string) => {
    const v = revealed[name];
    if (!v) {
      try {
        const d = await api.revealKey(name);
        await navigator.clipboard.writeText(d.value);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "copy failed");
        return;
      }
    } else {
      await navigator.clipboard.writeText(v);
    }
    setCopied(name);
    setTimeout(() => setCopied(null), 1500);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Vault</h1>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-[var(--color-muted-foreground)]" />
            <Input
              placeholder="Search keys or providers…"
              className="pl-8 w-64"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </Button>
        </div>
      </div>

      {err && (
        <div className="rounded-md border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/10 p-3 text-sm text-[var(--color-destructive)]">
          {err}
        </div>
      )}

      <div className="rounded-md border bg-[var(--color-card)]">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Key</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>Env</TableHead>
              <TableHead>Value</TableHead>
              <TableHead>Rotated</TableHead>
              <TableHead>Backup</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && !loading ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-[var(--color-muted-foreground)] py-8">
                  {keys.length === 0 ? "Vault is empty. Add keys via the desktop app or CLI." : "No matches."}
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((k) => (
                <TableRow key={k.name}>
                  <TableCell className="font-mono text-xs">{k.name}</TableCell>
                  <TableCell>
                    <span className="text-sm text-[var(--color-muted-foreground)]">{k.provider ?? "—"}</span>
                  </TableCell>
                  <TableCell>
                    <Badge variant={envVariant(k.env)}>{k.env}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {revealed[k.name] ?? k.masked}
                  </TableCell>
                  <TableCell className="text-xs text-[var(--color-muted-foreground)]">
                    {k.rotated ?? "—"}
                  </TableCell>
                  <TableCell>
                    {k.has_backup ? <Badge variant="success">staged</Badge> : k.dual_rotation ? <Badge variant="warning">missing</Badge> : <span className="text-xs text-[var(--color-muted-foreground)]">—</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="icon" onClick={() => reveal(k.name)} title="Reveal">
                        {revealed[k.name] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => copy(k.name)} title="Copy">
                        {copied === k.name ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
