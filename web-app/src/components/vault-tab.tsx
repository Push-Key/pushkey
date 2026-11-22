"use client";

import { useEffect, useRef, useState, useMemo, Fragment, useId } from "react";
import {
  Eye, EyeOff, Search, Copy, Check, Plus, Trash2, RefreshCw, X,
  Layers, ArrowUpCircle, Pencil, FolderTree, Link2,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  api,
  ApiError,
  describeApiError,
  reasonText,
  type ConnectionStatus,
  type ConnectResult,
  type KeySummary,
  type Preview,
  type Project,
  type RotateResp,
  type Suggestion,
} from "@/lib/api";
import { toast } from "@/lib/toast";
import {
  ConfirmPanel,
  ResultLines,
  StateBadge,
  canUpdate,
  projectLabel,
} from "@/components/connect-ui";

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

/** What the "Used in" row of one key shows. Present in the map only while the row is open. */
interface UsedIn {
  loading: boolean;
  rows: ConnectionStatus[];
  err: string | null;
  results: ConnectResult[] | null;
  busy: string | null;
}

/** The result panel shown after an add that was connected to a project. */
interface AddResult {
  name: string;
  connection: ConnectResult;
}

const PREVIEW_DEBOUNCE_MS = 400;

const changeSentence = (p: Preview) => {
  if (p.change === "replace") {
    return `Replaces the current value of ${p.var} in ${p.file}. The other lines stay as they are.`;
  }
  if (p.change === "none") return `${p.file} already has this value.`;
  return `Adds 1 line to ${p.file}. The other lines stay as they are.`;
};

interface EditForm {
  provider: string;
  env: string;
  notes: string;
}

const EMPTY_ADD: AddForm = { name: "", value: "", provider: "", env: "dev" };
const REVEAL_TIMEOUT_MS = 10_000;
const CLIPBOARD_CLEAR_TIMEOUT_MS = 30_000;
const COPIED_INDICATOR_TIMEOUT_MS = 1_500;

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

  // Connect section of the add-key form
  const [projects, setProjects] = useState<Project[]>([]);
  const [connectOn, setConnectOn] = useState(false);
  const [connectTouched, setConnectTouched] = useState(false);
  const [project, setProject] = useState("");
  const [file, setFile] = useState("");
  const [varName, setVarName] = useState("");
  const [otherVar, setOtherVar] = useState("");
  const [suggest, setSuggest] = useState<Suggestion | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [confirmNeeds, setConfirmNeeds] = useState<string[] | null>(null);
  const [addResult, setAddResult] = useState<AddResult | null>(null);
  const confirmRef = useRef<HTMLDivElement>(null);
  const submitRef = useRef<HTMLButtonElement>(null);

  // "Used in" rows and the outcome of the last rotate or promote, per key
  const [usedInState, setUsedInState] = useState<Record<string, UsedIn>>({});
  const [rotateResults, setRotateResults] = useState<Record<string, RotateResp>>({});
  const searchId = useId();
  const addFormId = useId();
  const confirmTitleId = useId();
  const addResultTitleId = useId();
  const effectiveVar = otherVar.trim() || varName;

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

  const loadProjects = async () => {
    try {
      const r = await api.listProjects();
      setProjects(r.projects);
    } catch {
      /* names fall back to the folder name; the add form says when there are none */
    }
  };

  useEffect(() => { refresh(); loadProjects(); }, []);

  // ── connect section: suggestions, then a preview of exactly what would be written ──
  const resetConnect = () => {
    setConnectOn(false);
    setConnectTouched(false);
    setProject("");
    setFile("");
    setVarName("");
    setOtherVar("");
    setSuggest(null);
    setPreview(null);
    setPreviewErr(null);
    setPreviewBusy(false);
    setConfirmNeeds(null);
  };

  useEffect(() => {
    if (!showAdd || !addForm.name) { setSuggest(null); return; }
    let live = true;
    const timer = setTimeout(async () => {
      try {
        const s = await api.suggestConnection(addForm.name, project || undefined);
        if (!live) return;
        setSuggest(s);
        if (!connectTouched && s.projects.length > 0) setConnectOn(true);
        if (!project && s.projects.length > 0) setProject(s.projects[0][0]);
        if (s.files.length > 0 && !s.files.some(([f]) => f === file)) setFile(s.files[0][0]);
        if (s.vars.length > 0 && !s.vars.some(([v]) => v === varName)) setVarName(s.vars[0][0]);
      } catch {
        if (live) setSuggest(null);
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => { live = false; clearTimeout(timer); };
    // file and varName are read to keep a choice that is still offered; they must not retrigger the lookup
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showAdd, addForm.name, project, connectTouched]);

  useEffect(() => {
    setConfirmNeeds(null);
    if (!connectOn || !addForm.name || !addForm.value || !project) {
      setPreview(null);
      setPreviewErr(null);
      setPreviewBusy(false);
      return;
    }
    let live = true;
    setPreviewBusy(true);
    const timer = setTimeout(async () => {
      try {
        const p = await api.previewConnection({
          key: addForm.name,
          project,
          file: file || undefined,
          var: effectiveVar || undefined,
          value: addForm.value,
          env: addForm.env || undefined,
        });
        if (!live) return;
        setPreview(p);
        setPreviewErr(null);
      } catch (e) {
        if (!live) return;
        setPreview(null);
        setPreviewErr(describeApiError(e, "Could not check that file"));
      } finally {
        if (live) setPreviewBusy(false);
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => { live = false; clearTimeout(timer); };
  }, [connectOn, addForm.name, addForm.value, addForm.env, project, file, effectiveVar]);

  useEffect(() => {
    if (confirmNeeds) confirmRef.current?.focus();
  }, [confirmNeeds]);

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
      }, REVEAL_TIMEOUT_MS);
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
    setTimeout(() => setCopied(null), COPIED_INDICATOR_TIMEOUT_MS);
    setTimeout(() => {
      navigator.clipboard.writeText("").catch(() => {});
    }, CLIPBOARD_CLEAR_TIMEOUT_MS);
  };

  const submitAdd = async (confirmed?: string[]) => {
    setAddLoading(true);
    setErr(null);
    try {
      const connect = connectOn && project
        ? {
            project,
            file: file || undefined,
            var: effectiveVar || undefined,
            ...(confirmed && confirmed.length > 0 ? { confirmed } : {}),
          }
        : undefined;
      const added = await api.addKey({
        name: addForm.name,
        value: addForm.value,
        provider: addForm.provider || undefined,
        env: addForm.env || undefined,
        connect,
      });
      setShowAdd(false);
      setAddForm(EMPTY_ADD);
      resetConnect();
      await refresh();
      if (added.connection) {
        setAddResult({ name: added.name, connection: added.connection });
      } else {
        toast.success("Key added");
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail === "confirmation_required" && e.needs.length > 0) {
        setConfirmNeeds(e.needs);
      } else {
        setErr(describeApiError(e, "add failed"));
      }
    } finally {
      setAddLoading(false);
    }
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addForm.name || !addForm.value || confirmNeeds) return;
    if (connectOn) {
      if (!project || !preview || previewErr || previewBusy) return;
      if (preview.needs_confirm.length > 0) {
        setConfirmNeeds(preview.needs_confirm);
        return;
      }
    }
    await submitAdd();
  };

  const handleDelete = async (name: string) => {
    if (!window.confirm(`Delete key "${name}"? This cannot be undone.`)) return;
    setErr(null);
    try {
      await api.deleteKey(name);
      await refresh();
      toast.success("Key deleted");
      document.getElementById(searchId)?.focus();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "delete failed");
    }
  };

  // ── inline row openers (mutually exclusive per row) ─────────────────────────
  // Return focus to the toggle button that controls an inline row (WCAG: avoid
  // dropping focus to <body> when the row unmounts).
  const focusToggleFor = (rowDomId: string) => {
    document.querySelector<HTMLElement>(`[aria-controls="${rowDomId}"]`)?.focus();
  };

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
      const r = await api.rotateKey(name, newVal);
      closeAllFor(name);
      setRotateResults((p) => ({ ...p, [name]: r }));
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
      const r = await api.promote(name);
      setRotateResults((p) => ({ ...p, [name]: r }));
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "promote failed");
    } finally {
      setPromoteLoading(null);
    }
  };

  // ── "Used in" row ───────────────────────────────────────────────────────────
  const patchUsedIn = (name: string, patch: Partial<UsedIn>) =>
    setUsedInState((p) => (p[name] ? { ...p, [name]: { ...p[name], ...patch } } : p));

  const loadUsedIn = async (name: string) => {
    try {
      const r = await api.listConnections({ key: name });
      patchUsedIn(name, { loading: false, rows: r.connections, err: null });
    } catch (e) {
      patchUsedIn(name, { loading: false, err: describeApiError(e, "Could not load where this key is used") });
    }
  };

  const toggleUsedIn = (name: string) => {
    if (usedInState[name] !== undefined) {
      setUsedInState((p) => { const n = { ...p }; delete n[name]; return n; });
      return;
    }
    setUsedInState((p) => ({ ...p, [name]: { loading: true, rows: [], err: null, results: null, busy: null } }));
    loadUsedIn(name);
  };

  const handleUpdateNow = async (name: string, c: ConnectionStatus) => {
    patchUsedIn(name, { busy: `${c.project}|${c.file}|${c.var}`, err: null });
    try {
      const r = await api.syncConnections({ key: name, project: c.project });
      patchUsedIn(name, { results: r.synced, busy: null });
    } catch (e) {
      patchUsedIn(name, { busy: null, err: describeApiError(e, "update failed") });
    }
    await loadUsedIn(name);
  };

  const handleDisconnect = async (name: string, usedInId: string, c: ConnectionStatus) => {
    if (!window.confirm(
      `Disconnect "${name}" from ${c.project_name} (${c.file})? The line stays in ${c.file}; Pushkey will stop updating it.`,
    )) return;
    patchUsedIn(name, { busy: `${c.project}|${c.file}|${c.var}`, err: null });
    try {
      await api.disconnect({ key: name, project: c.project, file: c.file, var: c.var });
      patchUsedIn(name, { busy: null, results: null });
      await Promise.all([loadUsedIn(name), refresh()]);
      toast.success("Disconnected");
    } catch (e) {
      patchUsedIn(name, { busy: null, err: describeApiError(e, "disconnect failed") });
    }
    focusToggleFor(usedInId);
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

  const hasOutcome = (r: RotateResp) =>
    (r.synced?.length ?? 0) > 0 || (r.not_synced?.length ?? 0) > 0 || !!r.sync_error;

  const openUsedIn = (name: string) => {
    setAddResult(null);
    if (usedInState[name] === undefined) toggleUsedIn(name);
    setTimeout(() => focusToggleFor(`used-in-row-${encodeURIComponent(name)}`), 0);
  };

  // ── row renderer ────────────────────────────────────────────────────────────
  const renderRow = (k: KeySummary) => {
    const rowId = encodeURIComponent(k.name);
    const rotateRowId = `rotate-row-${rowId}`;
    const backupRowId = `backup-row-${rowId}`;
    const editRowId = `edit-row-${rowId}`;
    const usedInId = `used-in-row-${rowId}`;
    const usedIn = usedInState[k.name];
    const rotated = rotateResults[k.name];
    return (
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
          {k.rotated ? k.rotated.slice(0, 10) : "—"}
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
            <Button variant="ghost" size="icon" onClick={() => reveal(k.name)} title="Reveal" aria-label={`Reveal ${k.name}`} aria-pressed={!!revealed[k.name]}>
              {revealed[k.name] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="icon" onClick={() => copy(k.name)} title="Copy" aria-label={`Copy ${k.name}`}>
              {copied === k.name ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              title="Where it is used"
              aria-label={`Used in ${k.name}`}
              aria-expanded={usedInState[k.name] !== undefined}
              aria-controls={usedInId}
              className="h-9 gap-1 px-2 text-cyan-400 hover:text-cyan-300"
              onClick={() => toggleUsedIn(k.name)}
            >
              <Link2 className="h-4 w-4" />
              <span aria-hidden="true" className="text-xs">{k.connections ?? 0}</span>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title="Edit metadata"
              aria-label={`Edit metadata for ${k.name}`}
              aria-expanded={editState[k.name] !== undefined}
              aria-controls={editRowId}
              onClick={() => toggleEdit(k)}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title="Set backup"
              aria-label={`Set backup for ${k.name}`}
              aria-expanded={backupState[k.name] !== undefined}
              aria-controls={backupRowId}
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
                aria-label={`Promote backup for ${k.name}`}
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
              aria-label={`Rotate ${k.name}`}
              aria-expanded={rotateState[k.name] !== undefined}
              aria-controls={rotateRowId}
              className="text-orange-400 hover:text-orange-300"
              onClick={() => toggleRotate(k.name)}
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title="Delete"
              aria-label={`Delete ${k.name}`}
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
        <TableRow id={rotateRowId} className="bg-orange-500/5">
          <TableCell colSpan={7} className="py-2 px-4">
            <div className="flex items-center gap-2">
              <span className="text-xs text-orange-400 font-medium whitespace-nowrap">New value for {k.name}</span>
              <Input
                type="password"
                aria-label={`New value for ${k.name}`}
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
              <Button variant="ghost" size="sm" className="h-8 text-[var(--color-muted-foreground)]" onClick={() => { closeAllFor(k.name); focusToggleFor(rotateRowId); }}>
                Cancel
              </Button>
            </div>
            {(k.connections ?? 0) > 0 && (
              <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
                Pushkey will update every connected file ({k.connections}). The old value stays in the key&apos;s history.
              </p>
            )}
          </TableCell>
        </TableRow>
      )}

      {/* Inline backup row */}
      {backupState[k.name] !== undefined && (
        <TableRow id={backupRowId} className="bg-cyan-500/5">
          <TableCell colSpan={7} className="py-2 px-4">
            <div className="flex items-center gap-2">
              <span className="text-xs text-cyan-400 font-medium whitespace-nowrap">Backup value for {k.name}</span>
              <Input
                type="password"
                aria-label={`Backup value for ${k.name}`}
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
              <Button variant="ghost" size="sm" className="h-8 text-[var(--color-muted-foreground)]" onClick={() => { closeAllFor(k.name); focusToggleFor(backupRowId); }}>
                Cancel
              </Button>
            </div>
          </TableCell>
        </TableRow>
      )}

      {/* Inline edit metadata row */}
      {editState[k.name] !== undefined && (
        <TableRow id={editRowId} className="bg-[var(--color-muted-foreground)]/5">
          <TableCell colSpan={7} className="py-2 px-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-medium whitespace-nowrap">Edit {k.name}</span>
              <Input
                aria-label={`Provider for ${k.name}`}
                placeholder="provider"
                className="text-xs h-8 max-w-[160px]"
                value={editState[k.name].provider}
                onChange={(e) => setEditState((p) => ({ ...p, [k.name]: { ...p[k.name], provider: e.target.value } }))}
              />
              <select
                aria-label={`Environment for ${k.name}`}
                value={editState[k.name].env}
                onChange={(e) => setEditState((p) => ({ ...p, [k.name]: { ...p[k.name], env: e.target.value } }))}
                className="flex h-8 rounded-md border border-input bg-transparent px-2 py-1 text-xs"
              >
                {ENV_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
              <Input
                aria-label={`Notes for ${k.name}`}
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
              <Button variant="ghost" size="sm" className="h-8 text-[var(--color-muted-foreground)]" onClick={() => { closeAllFor(k.name); focusToggleFor(editRowId); }}>
                Cancel
              </Button>
            </div>
          </TableCell>
        </TableRow>
      )}

      {/* What the last rotate or promote did to the connected files */}
      {rotated && hasOutcome(rotated) && (
        <TableRow className="bg-[var(--color-muted-foreground)]/5">
          <TableCell colSpan={7} className="py-2 px-4">
            <div className="flex items-start justify-between gap-2">
              <div className="space-y-1">
                <p className="text-xs font-medium">Project files for {k.name}</p>
                {rotated.synced && rotated.synced.length > 0 && (
                  <ResultLines results={rotated.synced} projects={projects} />
                )}
                {rotated.not_synced && rotated.not_synced.length > 0 && (
                  <p role="status" className="text-xs text-amber-400">
                    Not updated (this session cannot write project files):{" "}
                    {rotated.not_synced.map((n) => `${projectLabel(n.project, projects)} ${n.file}`).join(", ")}
                  </p>
                )}
                {rotated.sync_error && (
                  <p role="alert" className="text-xs text-red-400">
                    The key was replaced, but the files could not be updated: {reasonText(rotated.sync_error)}. Use Update now.
                  </p>
                )}
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-[var(--color-muted-foreground)]"
                aria-label={`Dismiss update results for ${k.name}`}
                onClick={() => setRotateResults((p) => { const n = { ...p }; delete n[k.name]; return n; })}
              >
                Dismiss
              </Button>
            </div>
          </TableCell>
        </TableRow>
      )}

      {/* Inline "Used in" row */}
      {usedIn !== undefined && (
        <TableRow id={usedInId} className="bg-cyan-500/5">
          <TableCell colSpan={7} className="py-3 px-4">
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
                {usedIn.loading
                  ? "Used in"
                  : `Used in ${usedIn.rows.length} ${usedIn.rows.length === 1 ? "place" : "places"}`}
              </p>
              {usedIn.err && (
                <p role="alert" className="text-xs text-red-400">{usedIn.err}</p>
              )}
              {usedIn.loading && (
                <p className="text-xs text-[var(--color-muted-foreground)]">Loading…</p>
              )}
              {!usedIn.loading && !usedIn.err && usedIn.rows.length === 0 && (
                <p className="text-sm text-[var(--color-muted-foreground)]">
                  Not used in any project yet. Connect it from Add key or the project&apos;s page.
                </p>
              )}
              {usedIn.rows.length > 0 && (
                <ul className="divide-y divide-[var(--color-border)]">
                  {usedIn.rows.map((c) => {
                    const rid = `${c.project}|${c.file}|${c.var}`;
                    return (
                      <li key={rid} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                        <span className="min-w-[8rem] text-sm font-medium">{c.project_name}</span>
                        <span className="font-mono text-xs">{c.file}</span>
                        <span className="font-mono text-xs text-[var(--color-muted-foreground)]">{c.var}</span>
                        <StateBadge state={c.state} />
                        {c.reason && (
                          <span className="text-xs text-[var(--color-muted-foreground)]">{reasonText(c.reason)}</span>
                        )}
                        <span className="ml-auto flex gap-1">
                          {canUpdate(c.state, c.reason) && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-8"
                              aria-label={`Update ${k.name} in ${c.project_name}`}
                              disabled={usedIn.busy !== null}
                              onClick={() => handleUpdateNow(k.name, c)}
                            >
                              Update now
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-8"
                            aria-label={`Disconnect ${k.name} from ${c.project_name} ${c.file}`}
                            disabled={usedIn.busy !== null}
                            onClick={() => handleDisconnect(k.name, usedInId, c)}
                          >
                            Disconnect
                          </Button>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
              {usedIn.results && usedIn.results.length > 0 && (
                <ResultLines
                  results={usedIn.results}
                  projects={[
                    ...usedIn.rows.map((c) => ({
                      path: c.project, name: c.project_name, keys: [], created: null, connections: 0,
                    })),
                    ...projects,
                  ]}
                />
              )}
            </div>
          </TableCell>
        </TableRow>
      )}
    </Fragment>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Vault</h1>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Label htmlFor={searchId} className="sr-only">Search keys or providers</Label>
            <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-[var(--color-muted-foreground)]" />
            <Input
              id={searchId}
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
            type="button"
            size="sm"
            className="gap-1 bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20"
            aria-expanded={showAdd}
            aria-controls={addFormId}
            onClick={() => {
              setShowAdd((v) => !v);
              setAddForm(EMPTY_ADD);
              resetConnect();
              setAddResult(null);
              if (!showAdd) loadProjects();
            }}
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
                type="button"
                aria-pressed={active}
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
          aria-pressed={groupByProvider}
          onClick={() => setGroupByProvider((v) => !v)}
        >
          <FolderTree className="h-4 w-4" />
          {groupByProvider ? "Grouped" : "Group by provider"}
        </Button>
      </div>

      {/* Add key inline form */}
      {showAdd && (
        <form
          id={addFormId}
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

          {/* Connect to a project */}
          <div className="space-y-3 border-t border-[var(--color-border)] pt-3">
            <div className="flex items-center gap-2">
              <input
                id="add-connect"
                type="checkbox"
                className="h-4 w-4 accent-cyan-400"
                checked={connectOn}
                onChange={(e) => {
                  setConnectTouched(true);
                  setConnectOn(e.target.checked);
                  if (e.target.checked && !project) {
                    setProject(suggest?.projects[0]?.[0] ?? projects[0]?.path ?? "");
                  }
                }}
              />
              <Label htmlFor="add-connect" className="text-sm font-semibold">Connect to a project</Label>
            </div>

            {!connectOn && (
              <p className="rounded-md border bg-[var(--color-muted)] p-3 text-sm">
                Saved in the vault only. Nothing is written to a project.
              </p>
            )}

            {connectOn && (
              <div className="space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label htmlFor="add-project" className="text-xs">Project</Label>
                    <select
                      id="add-project"
                      value={project}
                      onChange={(e) => { setProject(e.target.value); setFile(""); setVarName(""); }}
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    >
                      {projects.length === 0 ? (
                        <option value="">Add a project folder in the Projects tab first</option>
                      ) : (
                        <>
                          {!project && <option value="">Choose a project</option>}
                          {projects.map((p) => (
                            <option key={p.path} value={p.path}>{p.name || p.path}</option>
                          ))}
                        </>
                      )}
                    </select>
                    {suggest?.projects.find(([v]) => v === project) && (
                      <p className="text-xs text-[var(--color-muted-foreground)]">
                        Suggested: {suggest.projects.find(([v]) => v === project)?.[1]}
                      </p>
                    )}
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="add-file" className="text-xs">File in the project</Label>
                    <select
                      id="add-file"
                      value={file}
                      onChange={(e) => setFile(e.target.value)}
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 font-mono text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    >
                      {(suggest && suggest.files.length > 0 ? suggest.files : [[".env", "default env file"]]).map(([f]) => (
                        <option key={f} value={f}>{f}</option>
                      ))}
                    </select>
                    {suggest?.files.find(([v]) => v === file) && (
                      <p className="text-xs text-[var(--color-muted-foreground)]">
                        Suggested: {suggest.files.find(([v]) => v === file)?.[1]}
                      </p>
                    )}
                  </div>
                </div>

                <fieldset className="space-y-2">
                  <legend className="text-xs font-medium">Variable name the project reads</legend>
                  <div className="flex flex-wrap gap-2">
                    {(suggest?.vars ?? []).map(([name, why]) => (
                      <button
                        key={name}
                        type="button"
                        aria-pressed={!otherVar.trim() && varName === name}
                        onClick={() => { setVarName(name); setOtherVar(""); }}
                        className={
                          "flex flex-col items-start rounded-md border px-3 py-1.5 text-left transition-colors " +
                          (!otherVar.trim() && varName === name
                            ? "border-cyan-500/60 bg-cyan-500/10"
                            : "border-[var(--color-border)] hover:bg-[var(--color-muted)]")
                        }
                      >
                        <span className="font-mono text-xs">{name}</span>{" "}
                        <span className="text-xs text-[var(--color-muted-foreground)]">{why}</span>
                      </button>
                    ))}
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="add-var-other" className="text-xs">Other name</Label>
                    <Input
                      id="add-var-other"
                      className="max-w-xs font-mono text-xs"
                      placeholder="OPENAI_API_KEY"
                      value={otherVar}
                      onChange={(e) => setOtherVar(e.target.value.toUpperCase())}
                    />
                  </div>
                </fieldset>

                {previewErr && (
                  <p role="alert" className="rounded-md border border-red-400/30 bg-red-500/5 p-3 text-sm text-red-400">
                    {previewErr}
                  </p>
                )}
                <div aria-live="polite">
                  {preview && !previewErr && (
                    <div className="space-y-1 rounded-md border border-cyan-500/40 bg-cyan-500/5 p-3">
                      <p className="text-sm">{preview.line}</p>
                      <p className="text-xs text-[var(--color-muted-foreground)]">{changeSentence(preview)}</p>
                      <p className="text-xs text-[var(--color-muted-foreground)]">
                        {preview.gitignore_change
                          ? `${preview.file} will be added to .gitignore.`
                          : `${preview.file} is already ignored by git.`}
                      </p>
                    </div>
                  )}
                  {!preview && !previewErr && previewBusy && (
                    <p className="text-xs text-[var(--color-muted-foreground)]">Checking what would be written…</p>
                  )}
                </div>

                {confirmNeeds && (
                  <ConfirmPanel
                    ref={confirmRef}
                    titleId={confirmTitleId}
                    needs={confirmNeeds}
                    busy={addLoading}
                    onConfirm={() => submitAdd(confirmNeeds)}
                    onBack={() => { setConfirmNeeds(null); submitRef.current?.focus(); }}
                  />
                )}
              </div>
            )}
          </div>

          <div className="flex justify-end">
            <Button
              ref={submitRef}
              type="submit"
              size="sm"
              disabled={addLoading || (connectOn && (!project || previewBusy || !preview))}
              className="gap-1"
            >
              <Plus className="h-4 w-4" />
              {addLoading ? "Saving…" : connectOn ? "Save & connect" : "Save"}
            </Button>
          </div>
        </form>
      )}

      {addResult && (
        <section
          aria-labelledby={addResultTitleId}
          className="space-y-2 rounded-md border border-emerald-400/30 bg-emerald-500/5 p-4"
        >
          <h2 id={addResultTitleId} className="text-base font-semibold">
            {addResult.name} is saved and connected
          </h2>
          <div role="status" aria-live="polite" className="space-y-1 text-sm">
            <p>Saved in the vault, encrypted with your master password</p>
            <p>
              {`Connected: ${projectLabel(addResult.connection.project, projects)} -> ${addResult.connection.file} as ${addResult.connection.var}`}
            </p>
            {addResult.connection.written && (
              <p>
                {`Written: ${addResult.connection.change === "replace" ? "1 line replaced" : addResult.connection.change === "none" ? "no change needed" : "1 line added"}`}
                {addResult.connection.gitignore_changed ? `, ${addResult.connection.file} added to .gitignore` : ""}
              </p>
            )}
          </div>
          {!addResult.connection.written && (
            <p role="alert" className="text-sm text-red-400">
              {`Not written: ${reasonText(addResult.connection.reason)}. The key is saved and connected; fix that, then use Update now.`}
            </p>
          )}
          <p className="text-xs text-[var(--color-muted-foreground)]">
            Pushkey remembers this connection. When you replace the key, this file is updated too.
          </p>
          <div className="flex gap-2">
            <Button type="button" size="sm" onClick={() => openUsedIn(addResult.name)}>
              See where it is used
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                setAddResult(null);
                setShowAdd(true);
                setAddForm(EMPTY_ADD);
                resetConnect();
                loadProjects();
              }}
            >
              Add another key
            </Button>
          </div>
        </section>
      )}

      {err && (
        <div
          role="alert"
          aria-live="assertive"
          className="rounded-md border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/10 p-3 text-sm text-[var(--color-destructive)]"
        >
          {err}
        </div>
      )}

      <p role="status" aria-live="polite" className="sr-only">
        {copied ? `Copied ${copied} to clipboard` : ""}
      </p>

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
