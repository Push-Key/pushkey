"use client";

import { useEffect, useState, useMemo, Fragment } from "react";
import {
  Eye, EyeOff, Search, Copy, Check, Plus, Trash2, RefreshCw, X,
  Layers, ArrowUpCircle, Pencil, FolderTree,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type KeySummary } from "@/lib/api";
import { toast } from "@/lib/toast";

const envVariant = (env: string) => {
  if (env === "prod")    return "destructive" as const;
  if (env === "staging") return "warning" as const;
  if (env === "dev")     return "success" as const;
  return "secondary" as const;
};

const ENV_OPTIONS = ["dev", "staging", "prod", "all"] as const;
type EnvFilter = "all" | "dev" | "staging" | "prod" | "all-env";
const FILTER_PILLS: { id: EnvFilter; label: string }[] = [
  { id: "all",     label: "All"     },
  { id: "dev",     label: "Dev"     },
  { id: "staging", label: "Staging" },
  { id: "prod",    label: "Prod"    },
  { id: "all-env", label: "All-env" },
];

interface AddForm {
  name: string;
  value: string;
  provider: string;
  env: string;
}

interface EditForm {
  provider: string;
  env: string;
  notes: string;
}

const EMPTY_ADD: AddForm = { name: "", value: "", provider: "", env: "dev" };

export function VaultTab() {
  const [keys, setKeys] = useState<KeySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [envFilter, setEnvFilter] = useState<EnvFilter>("all");
  const [groupByProvider, setGroupByProvider] = useState(false);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState<string | null>(null);

  // Add key form
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState<AddForm>(EMPTY_ADD);
  const [addLoading, setAddLoading] = useState(false);

  // Inline row state — only one type open at a time per row
  const [rotateState, setRotateState] = useState<Record<string, string>>({});
  const [rotateLoading, setRotateLoading] = useState<string | null>(null);

  const [backupState, setBackupState] = useState<Record<string, string>>({});
  const [backupLoading, setBackupLoading] = useState<string | null>(null);

  const [editState, setEditState] = useState<Record<string, EditForm>>({});
  const [editLoading, setEditLoading] = useState<string | null>(null);

  const [promoteLoading, setPromoteLoading] = useState<string | null>(null);

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
    return keys.filter((k) => {
      if (f && !k.name.toLowerCase().includes(f) && !(k.provider ?? "").toLowerCase().includes(f)) return false;
      if (envFilter === "all") return true;
      if (envFilter === "all-env") return k.env === "all";
      return k.env === envFilter;
    });
  }, [keys, filter, envFilter]);

  const grouped = useMemo(() => {
    if (!groupByProvider) return null;
    const map = new Map<string, KeySummary[]>();
    for (const k of filtered) {
      const p = k.provider ?? "(no provider)";
      if (!map.has(p)) map.set(p, []);
      map.get(p)!.push(k);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered, groupByProvider]);

  const reveal = async (name: string) => {
    if (revealed[name]) {
      setRevealed((p) => { const n = { ...p }; delete n[name]; return n; });
      return;
    }
    try {
      const detail = await api.revealKey(name);
      setRevealed((p) => ({ ...p, [name]: detail.value }));
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

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addForm.name || !addForm.value) return;
    setAddLoading(true);
    setErr(null);
    try {
      await api.addKey({
        name: addForm.name,
        value: addForm.value,
        provider: addForm.provider || undefined,
        env: addForm.env || undefined,
      });
      setShowAdd(false);
      setAddForm(EMPTY_ADD);
      await refresh();
      toast.success("Key added");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "add failed");
    } finally {
      setAddLoading(false);
    }
  };

  const handleDelete = async (name: string) => {
    if (!window.confirm(`Delete key "${name}"? This cannot be undone.`)) return;
    setErr(null);
    try {
      await api.deleteKey(name);
      await refresh();
      toast.success("Key deleted");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "delete failed");
    }
  };

  // ── inline row openers (mutually exclusive per row) ─────────────────────────
  const closeAllFor = (name: string) => {
    setRotateState((p) => { const n = { ...p }; delete n[name]; return n; });
    setBackupState((p) => { const n = { ...p }; delete n[name]; return n; });
    setEditState((p)   => { const n = { ...p }; delete n[name]; return n; });
  };

  const toggleRotate = (name: string) => {
    if (rotateState[name] !== undefined) closeAllFor(name);
    else { closeAllFor(name); setRotateState((p) => ({ ...p, [name]: "" })); }
  };
  const toggleBackup = (name: string) => {
    if (backupState[name] !== undefined) closeAllFor(name);
    else { closeAllFor(name); setBackupState((p) => ({ ...p, [name]: "" })); }
  };
  const toggleEdit = (k: KeySummary) => {
    if (editState[k.name] !== undefined) closeAllFor(k.name);
    else {
      closeAllFor(k.name);
      setEditState((p) => ({ ...p, [k.name]: { provider: k.provider ?? "", env: k.env, notes: "" } }));
    }
  };

  const handleRotate = async (name: string) => {
    const newVal = rotateState[name];
    if (!newVal) return;
    setRotateLoading(name);
    setErr(null);
    try {
      await api.rotateKey(name, newVal);
      closeAllFor(name);
      await refresh();
      toast.success("Key rotated");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "rotate failed");
    } finally {
      setRotateLoading(null);
    }
  };

  const handleSetBackup = async (name: string) => {
    const v = backupState[name];
    if (!v) return;
    setBackupLoading(name);
    setErr(null);
    try {
      await api.setBackup(name, v);
      closeAllFor(name);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "set backup failed");
    } finally {
      setBackupLoading(null);
    }
  };

  const handlePromote = async (name: string) => {
    if (!window.confirm(`Promote staged backup for "${name}" to active key? The current value will be retired.`)) return;
    setPromoteLoading(name);
    setErr(null);
    try {
      await api.promote(name);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "promote failed");
    } finally {
      setPromoteLoading(null);
    }
  };

  const handleEditSave = async (name: string) => {
    const f = editState[name];
    if (!f) return;
    setEditLoading(name);
    setErr(null);
    try {
      await api.updateKey(name, {
        provider: f.provider || undefined,
        env: f.env || undefined,
        notes: f.notes || undefined,
      });
      closeAllFor(name);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "update failed");
    } finally {
      setEditLoading(null);
    }
  };

  // ── row renderer ────────────────────────────────────────────────────────────
  const renderRow = (k: KeySummary) => (
    <Fragment key={k.name}>
      <TableRow>
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
          {k.has_backup
            ? <Badge variant="success">staged</Badge>
            : k.dual_rotation
            ? <Badge variant="warning">missing</Badge>
            : <span className="text-xs text-[var(--color-muted-foreground)]">—</span>}
        </TableCell>
        <TableCell className="text-right">
          <div className="flex justify-end gap-0.5 flex-wrap">
            <Button variant="ghost" size="icon" onClick={() => reveal(k.name)} title="Reveal">
              {revealed[k.name] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="icon" onClick={() => copy(k.name)} title="Copy">
              {copied === k.name ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title="Edit metadata"
              onClick={() => toggleEdit(k)}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title="Set backup"
              className="text-cyan-400 hover:text-cyan-300"
              onClick={() => toggleBackup(k.name)}
            >
              <Layers className="h-4 w-4" />
            </Button>
            {k.has_backup && (
              <Button
                variant="ghost"
                size="icon"
                title="Promote backup"
                className="text-emerald-400 hover:text-emerald-300"
                onClick={() => handlePromote(k.name)}
                disabled={promoteLoading === k.name}
              >
                <ArrowUpCircle className="h-4 w-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              title="Rotate"
              className="text-orange-400 hover:text-orange-300"
              onClick={() => toggleRotate(k.name)}
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title="Delete"
              className="text-red-400 hover:text-red-300"
              onClick={() => handleDelete(k.name)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </TableCell>
      </TableRow>

      {/* Inline rotate row */}
      {rotateState[k.name] !== undefined && (
        <TableRow className="bg-orange-500/5">
          <TableCell colSpan={7} className="py-2 px-4">
            <div className="flex items-center gap-2">
              <span className="text-xs text-orange-400 font-medium whitespace-nowrap">New value for {k.name}</span>
              <Input
                type="password"
                placeholder="New secret value…"
                className="font-mono text-xs h-8 max-w-xs"
                value={rotateState[k.name]}
                onChange={(e) => setRotateState((p) => ({ ...p, [k.name]: e.target.value }))}
                autoFocus
              />
              <Button
                size="sm"
                className="h-8 gap-1 bg-orange-500/10 border border-orange-500/30 text-orange-400 hover:bg-orange-500/20"
                onClick={() => handleRotate(k.name)}
                disabled={!rotateState[k.name] || rotateLoading === k.name}
              >
                <RefreshCw className="h-3 w-3" />
                {rotateLoading === k.name ? "Rotating…" : "Rotate"}
              </Button>
              <Button variant="ghost" size="sm" className="h-8 text-[var(--color-muted-foreground)]" onClick={() => closeAllFor(k.name)}>
                Cancel
              </Button>
            </div>
          </TableCell>
        </TableRow>
      )}

      {/* Inline backup row */}
      {backupState[k.name] !== undefined && (
        <TableRow className="bg-cyan-500/5">
          <TableCell colSpan={7} className="py-2 px-4">
            <div className="flex items-center gap-2">
              <span className="text-xs text-cyan-400 font-medium whitespace-nowrap">Backup value for {k.name}</span>
              <Input
                type="password"
                placeholder="Stage backup secret…"
                className="font-mono text-xs h-8 max-w-xs"
                value={backupState[k.name]}
                onChange={(e) => setBackupState((p) => ({ ...p, [k.name]: e.target.value }))}
                autoFocus
              />
              <Button
                size="sm"
                className="h-8 gap-1 bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20"
                onClick={() => handleSetBackup(k.name)}
                disabled={!backupState[k.name] || backupLoading === k.name}
              >
                <Layers className="h-3 w-3" />
                {backupLoading === k.name ? "Staging…" : "Stage backup"}
              </Button>
              <Button variant="ghost" size="sm" className="h-8 text-[var(--color-muted-foreground)]" onClick={() => closeAllFor(k.name)}>
                Cancel
              </Button>
            </div>
          </TableCell>
        </TableRow>
      )}

      {/* Inline edit metadata row */}
      {editState[k.name] !== undefined && (
        <TableRow className="bg-[var(--color-muted-foreground)]/5">
          <TableCell colSpan={7} className="py-2 px-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-medium whitespace-nowrap">Edit {k.name}</span>
              <Input
                placeholder="provider"
                className="text-xs h-8 max-w-[160px]"
                value={editState[k.name].provider}
                onChange={(e) => setEditState((p) => ({ ...p, [k.name]: { ...p[k.name], provider: e.target.value } }))}
              />
              <select
                value={editState[k.name].env}
                onChange={(e) => setEditState((p) => ({ ...p, [k.name]: { ...p[k.name], env: e.target.value } }))}
                className="flex h-8 rounded-md border border-input bg-transparent px-2 py-1 text-xs"
              >
                {ENV_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
              <Input
                placeholder="notes"
                className="text-xs h-8 flex-1 min-w-[200px]"
                value={editState[k.name].notes}
                onChange={(e) => setEditState((p) => ({ ...p, [k.name]: { ...p[k.name], notes: e.target.value } }))}
              />
              <Button
                size="sm"
                className="h-8 gap-1"
                onClick={() => handleEditSave(k.name)}
                disabled={editLoading === k.name}
              >
                <Check className="h-3 w-3" />
                {editLoading === k.name ? "Saving…" : "Save"}
              </Button>
              <Button variant="ghost" size="sm" className="h-8 text-[var(--color-muted-foreground)]" onClick={() => closeAllFor(k.name)}>
                Cancel
              </Button>
            </div>
          </TableCell>
        </TableRow>
      )}
    </Fragment>
  );

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
          <Button
            size="sm"
            className="gap-1 bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20"
            onClick={() => { setShowAdd((v) => !v); setAddForm(EMPTY_ADD); }}
          >
            {showAdd ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            {showAdd ? "Cancel" : "Add key"}
          </Button>
        </div>
      </div>

      {/* Filter pills + group toggle */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-1">
          {FILTER_PILLS.map((p) => {
            const active = envFilter === p.id;
            return (
              <button
                key={p.id}
                onClick={() => setEnvFilter(p.id)}
                className={
                  "px-3 py-1 text-xs rounded-full border transition-colors " +
                  (active
                    ? "bg-cyan-500/20 border-cyan-500/40 text-cyan-300"
                    : "border-[var(--color-muted-foreground)]/20 text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted-foreground)]/10")
                }
              >
                {p.label}
              </button>
            );
          })}
        </div>
        <Button
          variant="outline"
          size="sm"
          className={"gap-1 " + (groupByProvider ? "border-cyan-500/40 text-cyan-300" : "")}
          onClick={() => setGroupByProvider((v) => !v)}
        >
          <FolderTree className="h-4 w-4" />
          {groupByProvider ? "Grouped" : "Group by provider"}
        </Button>
      </div>

      {/* Add key inline form */}
      {showAdd && (
        <form
          onSubmit={handleAdd}
          className="rounded-md border border-cyan-500/25 bg-[var(--color-card)] p-4 space-y-3"
        >
          <p className="text-sm font-medium text-cyan-400">New key</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="add-name" className="text-xs">Name *</Label>
              <Input
                id="add-name"
                placeholder="OPENAI_API_KEY"
                className="font-mono text-xs"
                value={addForm.name}
                onChange={(e) => setAddForm((f) => ({ ...f, name: e.target.value.toUpperCase() }))}
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="add-value" className="text-xs">Value *</Label>
              <Input
                id="add-value"
                type="password"
                placeholder="sk-…"
                className="font-mono text-xs"
                value={addForm.value}
                onChange={(e) => setAddForm((f) => ({ ...f, value: e.target.value }))}
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="add-provider" className="text-xs">Provider</Label>
              <Input
                id="add-provider"
                placeholder="openai"
                className="text-xs"
                value={addForm.provider}
                onChange={(e) => setAddForm((f) => ({ ...f, provider: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="add-env" className="text-xs">Env</Label>
              <select
                id="add-env"
                value={addForm.env}
                onChange={(e) => setAddForm((f) => ({ ...f, env: e.target.value }))}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {ENV_OPTIONS.map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="flex justify-end">
            <Button type="submit" size="sm" disabled={addLoading} className="gap-1">
              <Plus className="h-4 w-4" />
              {addLoading ? "Adding…" : "Add key"}
            </Button>
          </div>
        </form>
      )}

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
                  {keys.length === 0 ? "Vault is empty." : "No matches."}
                </TableCell>
              </TableRow>
            ) : grouped ? (
              grouped.map(([provider, rows]) => (
                <Fragment key={`group-${provider}`}>
                  <TableRow className="bg-cyan-500/5 hover:bg-cyan-500/10">
                    <TableCell colSpan={7} className="py-1.5 text-xs font-semibold text-cyan-300 uppercase tracking-wider">
                      {provider} <span className="text-[var(--color-muted-foreground)] font-normal normal-case">· {rows.length}</span>
                    </TableCell>
                  </TableRow>
                  {rows.map(renderRow)}
                </Fragment>
              ))
            ) : (
              filtered.map(renderRow)
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
