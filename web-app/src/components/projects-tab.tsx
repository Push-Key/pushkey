"use client";

import { useEffect, useId, useState } from "react";
import {
  FolderOpen, Plus, Trash2, ChevronDown, ChevronRight,
  Zap, Check, X, Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { api, type Project, type KeySummary } from "@/lib/api";
import { toast } from "@/lib/toast";

// ── helpers ───────────────────────────────────────────────────────────────────

function ErrorBanner({ msg }: { msg: string }) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="rounded-md border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/10 p-3 text-sm text-red-400"
    >
      {msg}
    </div>
  );
}

function InjectResult({
  result,
}: {
  result: { injected: string[]; skipped_existing: string[]; env_file: string; wrote: boolean };
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="rounded-md border border-emerald-400/20 bg-emerald-400/5 p-3 text-xs space-y-1"
    >
      <p className="font-semibold text-emerald-400">
        {result.wrote ? "Wrote" : "Preview"}: {result.env_file}
      </p>
      <p className="text-[var(--color-muted-foreground)]">
        Injected: {result.injected.length === 0 ? "none" : result.injected.join(", ")}
      </p>
      {result.skipped_existing.length > 0 && (
        <p className="text-orange-400">
          Conflict: existing values kept for {result.skipped_existing.join(", ")}
        </p>
      )}
    </div>
  );
}

// ── expanded project panel ────────────────────────────────────────────────────

function ProjectPanel({
  project,
  allKeys,
  onUpdate,
}: {
  project: Project;
  allKeys: KeySummary[];
  onUpdate: (p: Project) => void;
}) {
  const [injectLoading, setInjectLoading] = useState(false);
  const [injectResult, setInjectResult] = useState<{
    injected: string[]; skipped_existing: string[]; env_file: string; wrote: boolean;
  } | null>(null);
  const [injectErr, setInjectErr] = useState<string | null>(null);
  const [assignErr, setAssignErr] = useState<string | null>(null);
  const [assignLoading, setAssignLoading] = useState(false);

  const assigned = new Set(project.keys);
  const unassigned = allKeys.filter((k) => !assigned.has(k.name));
  const assignedKeys = allKeys.filter((k) => assigned.has(k.name));

  const inject = async () => {
    setInjectLoading(true);
    setInjectErr(null);
    setInjectResult(null);
    try {
      const r = await api.injectProject(project.path, false);
      setInjectResult(r);
      toast.success(".env injected");
    } catch (e) {
      setInjectErr(e instanceof Error ? e.message : "inject failed");
    } finally {
      setInjectLoading(false);
    }
  };

  const assign = async (keyName: string) => {
    setAssignLoading(true);
    setAssignErr(null);
    try {
      await api.assignKeys(project.path, [keyName]);
      onUpdate({ ...project, keys: [...project.keys, keyName] });
    } catch (e) {
      setAssignErr(e instanceof Error ? e.message : "assign failed");
    } finally {
      setAssignLoading(false);
    }
  };

  const unassign = async (keyName: string) => {
    setAssignLoading(true);
    setAssignErr(null);
    try {
      await api.unassignKeys(project.path, [keyName]);
      onUpdate({ ...project, keys: project.keys.filter((k) => k !== keyName) });
    } catch (e) {
      setAssignErr(e instanceof Error ? e.message : "unassign failed");
    } finally {
      setAssignLoading(false);
    }
  };

  return (
    <div className="border-t border-[var(--color-card)] bg-[var(--color-card)]/40 p-4 space-y-4">
      {/* Inject */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={inject}
            disabled={injectLoading}
            aria-label={`Inject environment file for ${project.name || project.path}`}
            className="border-cyan-400/30 text-cyan-400 hover:bg-cyan-400/10"
          >
            {injectLoading ? (
              <Loader2 className="h-3 w-3 animate-spin mr-1" />
            ) : (
              <Zap className="h-3 w-3 mr-1" />
            )}
            Inject .env
          </Button>
        </div>
        {injectErr && <ErrorBanner msg={injectErr} />}
        {injectResult && <InjectResult result={injectResult} />}
      </div>

      {/* Assigned keys */}
      <div className="space-y-1">
        <p className="text-xs font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider">
          Assigned keys ({project.keys.length})
        </p>
        {assignErr && <ErrorBanner msg={assignErr} />}
        {assignedKeys.length === 0 ? (
          <p className="text-xs text-[var(--color-muted-foreground)]">No keys assigned.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {assignedKeys.map((k) => (
              <div
                key={k.name}
                className="flex items-center gap-1 rounded-md border border-cyan-400/20 bg-cyan-400/5 px-2 py-1"
              >
                <span className="font-mono text-xs text-cyan-400">{k.name}</span>
                <button
                  type="button"
                  onClick={() => unassign(k.name)}
                  disabled={assignLoading}
                  aria-label={`Unassign ${k.name} from ${project.name || project.path}`}
                  className="text-[var(--color-muted-foreground)] hover:text-red-400 transition-colors ml-1"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Unassigned keys */}
      {unassigned.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider">
            Add keys
          </p>
          <div className="flex flex-wrap gap-2">
            {unassigned.map((k) => (
              <button
                type="button"
                key={k.name}
                onClick={() => assign(k.name)}
                disabled={assignLoading}
                aria-label={`Assign ${k.name} to ${project.name || project.path}`}
                className="flex items-center gap-1 rounded-md border border-[var(--color-card)] bg-[var(--color-card)] px-2 py-1 hover:border-cyan-400/30 hover:text-cyan-400 transition-colors"
              >
                <Plus className="h-3 w-3" />
                <span className="font-mono text-xs">{k.name}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── project card ──────────────────────────────────────────────────────────────

function ProjectCard({
  project,
  allKeys,
  onDelete,
  onUpdate,
}: {
  project: Project;
  allKeys: KeySummary[];
  onDelete: (path: string) => void;
  onUpdate: (p: Project) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);
  const panelId = useId();

  const handleDelete = async () => {
    if (!confirmDelete) { setConfirmDelete(true); return; }
    setDeleting(true);
    setDeleteErr(null);
    try {
      await api.deleteProject(project.path);
      onDelete(project.path);
    } catch (e) {
      setDeleteErr(e instanceof Error ? e.message : "delete failed");
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  return (
    <div className="rounded-lg border border-[var(--color-card)] bg-[var(--color-card)] overflow-hidden">
      {/* Header row */}
      <div className="flex items-center gap-3 p-4">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls={panelId}
          className="flex items-center gap-3 flex-1 text-left min-w-0"
        >
          {expanded
            ? <ChevronDown className="h-4 w-4 shrink-0 text-cyan-400" />
            : <ChevronRight className="h-4 w-4 shrink-0 text-[var(--color-muted-foreground)]" />}
          <FolderOpen className="h-4 w-4 shrink-0 text-cyan-400" />
          <div className="min-w-0">
            <p className="font-semibold truncate">{project.name || project.path}</p>
            <p className="text-xs text-[var(--color-muted-foreground)] font-mono truncate">
              {project.path}
            </p>
          </div>
        </button>

        <div className="flex items-center gap-2 shrink-0">
          <Badge variant="secondary" className="text-xs">
            {project.keys.length} {project.keys.length === 1 ? "key" : "keys"}
          </Badge>
          {project.created && (
            <span className="text-xs text-[var(--color-muted-foreground)] hidden sm:block">
              {new Date(project.created).toLocaleDateString()}
            </span>
          )}
          {confirmDelete ? (
            <div className="flex items-center gap-1">
              <Button
                type="button"
                size="sm"
                variant="destructive"
                onClick={handleDelete}
                disabled={deleting}
                aria-label={`Confirm delete for ${project.name || project.path}`}
                className="h-7 text-xs"
              >
                {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : "Confirm"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setConfirmDelete(false)}
                aria-label={`Cancel delete for ${project.name || project.path}`}
                className="h-7 text-xs"
              >
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              size="icon"
              variant="ghost"
              onClick={handleDelete}
              className="h-7 w-7 hover:text-red-400"
              aria-label={`Delete project ${project.name || project.path}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {deleteErr && (
        <div className="px-4 pb-3">
          <ErrorBanner msg={deleteErr} />
        </div>
      )}

      {expanded && (
        <div id={panelId} role="region" aria-label={`${project.name || project.path} project details`}>
          <ProjectPanel
            project={project}
            allKeys={allKeys}
            onUpdate={onUpdate}
          />
        </div>
      )}
    </div>
  );
}

// ── add project form ──────────────────────────────────────────────────────────

function AddProjectForm({ onAdded }: { onAdded: (p: Project) => void }) {
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!path.trim()) return;
    setLoading(true);
    setErr(null);
    setSuccess(false);
    try {
      const r = await api.createProject(path.trim(), name.trim() || undefined);
      onAdded({ path: r.path, name: r.name, keys: [], created: null });
      setPath("");
      setName("");
      setSuccess(true);
      toast.success("Project created");
      setTimeout(() => setSuccess(false), 2000);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "create failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-lg border border-[var(--color-card)] bg-[var(--color-card)] p-4 space-y-3"
    >
      <p className="text-sm font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider">
        Add project
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto_auto] gap-2">
        <div className="space-y-1">
          <Label htmlFor="proj-path" className="text-xs">Path</Label>
          <Input
            id="proj-path"
            placeholder="/home/user/my-project"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            className="font-mono text-sm"
            required
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="proj-name" className="text-xs">Name (optional)</Label>
          <Input
            id="proj-name"
            placeholder="My Project"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="text-sm"
          />
        </div>
        <div className="flex items-end">
          <Button
            type="submit"
            disabled={loading || !path.trim()}
            className="bg-cyan-400/10 border border-cyan-400/30 text-cyan-400 hover:bg-cyan-400/20 w-full sm:w-auto"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin mr-1" />
            ) : success ? (
              <Check className="h-4 w-4 mr-1 text-emerald-400" />
            ) : (
              <Plus className="h-4 w-4 mr-1" />
            )}
            {success ? "Added" : "Add"}
          </Button>
        </div>
      </div>
      {err && <ErrorBanner msg={err} />}
    </form>
  );
}

// ── main export ───────────────────────────────────────────────────────────────

export function ProjectsTab() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [allKeys, setAllKeys] = useState<KeySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setErr(null);
    try {
      const [pr, kr] = await Promise.all([api.listProjects(), api.listKeys()]);
      setProjects(pr.projects);
      setAllKeys(kr.keys);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const handleAdded = (p: Project) => setProjects((prev) => [p, ...prev]);

  const handleDelete = (path: string) =>
    setProjects((prev) => prev.filter((p) => p.path !== path));

  const handleUpdate = (updated: Project) =>
    setProjects((prev) => prev.map((p) => (p.path === updated.path ? updated : p)));

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
        <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
          {loading ? "Loading…" : "Refresh"}
        </Button>
      </div>

      {err && <ErrorBanner msg={err} />}

      {/* Add form */}
      <AddProjectForm onAdded={handleAdded} />

      {/* Project list */}
      {!loading && projects.length === 0 ? (
        <div className="rounded-lg border border-[var(--color-card)] bg-[var(--color-card)] p-8 text-center text-sm text-[var(--color-muted-foreground)]">
          No projects registered. Add one above.
        </div>
      ) : (
        <div className="space-y-2">
          {projects.map((p) => (
            <ProjectCard
              key={p.path}
              project={p}
              allKeys={allKeys}
              onDelete={handleDelete}
              onUpdate={handleUpdate}
            />
          ))}
        </div>
      )}
    </div>
  );
}
