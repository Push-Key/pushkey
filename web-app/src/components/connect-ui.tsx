"use client";

import { forwardRef } from "react";
import { Button } from "@/components/ui/button";
import {
  reasonText,
  type ConnectionState,
  type ConnectResult,
  type Project,
} from "@/lib/api";

// ── small helpers shared by the vault and projects screens ───────────────────

/** Compare two folder spellings the way the local API does (slashes, case on drive paths). */
export function samePath(a: string, b: string): boolean {
  const norm = (p: string) => {
    const s = p.replace(/\\/g, "/").replace(/\/+$/, "");
    return /^[a-zA-Z]:/.test(s) ? s.toLowerCase() : s;
  };
  return norm(a) === norm(b);
}

/** The registered name of a project folder, else its last path segment. */
export function projectLabel(path: string, projects: Project[]): string {
  const found = projects.find((p) => samePath(p.path, path));
  if (found?.name) return found.name;
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

export const NEEDS_TEXT: Record<string, string> = {
  env_mismatch: "This key is for another environment. Continue?",
  public_prefix: "This name is bundled into browser code. Continue?",
};

export function needsText(code: string): string {
  return NEEDS_TEXT[code] ?? "This needs your confirmation. Continue?";
}

// ── state badge ───────────────────────────────────────────────────────────────

const PILL = "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ";
const TONE_OK = PILL + "bg-emerald-500/15 text-emerald-400";
const TONE_WARN = PILL + "bg-amber-500/15 text-amber-400";
const TONE_QUIET = PILL + "bg-[var(--color-muted)] text-[var(--color-muted-foreground)]";
const TONE_BAD = PILL + "bg-red-500/15 text-red-400";

const STATE: Record<ConnectionState, { label: string; className: string }> = {
  up_to_date: { label: "Up to date", className: TONE_OK },
  out_of_date: { label: "Out of date", className: TONE_WARN },
  not_in_file: { label: "Not in the file yet", className: TONE_WARN },
  file_missing: { label: "File not created yet", className: TONE_WARN },
  not_ignored: { label: "Not in .gitignore", className: TONE_WARN },
  folder_missing: { label: "Folder not on this computer", className: TONE_QUIET },
  not_written: { label: "Not written", className: TONE_BAD },
};

export function StateBadge({ state }: { state: string }) {
  const known = STATE[state as ConnectionState];
  return <span className={known ? known.className : TONE_QUIET}>{known ? known.label : state}</span>;
}

/** True when "Update now" can change something for a connection in this state. */
export function canUpdate(state: string, reason: string | null): boolean {
  if (state === "not_written") return reason !== "file_tracked_by_git";
  return (
    state === "out_of_date" ||
    state === "not_in_file" ||
    state === "file_missing" ||
    state === "not_ignored"
  );
}

// ── results of a connect, sync or inject ──────────────────────────────────────

type Tone = "ok" | "skip" | "bad";

export function resultLine(r: ConnectResult, projects: Project[]): { tone: Tone; text: string } {
  const where = `${projectLabel(r.project, projects)} ${r.file}`;
  if (r.written) {
    return { tone: "ok", text: `${where}: ${r.change === "none" ? "Already up to date" : "Updated"}` };
  }
  if (r.reason === "folder_missing") {
    return { tone: "skip", text: `${where}: Skipped: folder not on this computer` };
  }
  return { tone: "bad", text: `${where}: Not written: ${reasonText(r.reason)}` };
}

/**
 * One line per file. Files that were not written are red and announced as
 * alerts; they are never folded into a success message.
 */
export function ResultLines({ results, projects }: { results: ConnectResult[]; projects: Project[] }) {
  const lines = results.map((r) => resultLine(r, projects));
  const fine = lines.filter((l) => l.tone !== "bad");
  const bad = lines.filter((l) => l.tone === "bad");
  return (
    <div className="space-y-1">
      {fine.length > 0 && (
        <div role="status" aria-live="polite" className="space-y-0.5 text-xs">
          {fine.map((l, i) => (
            <p
              key={`${l.text}-${i}`}
              className={l.tone === "ok" ? "text-emerald-400" : "text-[var(--color-muted-foreground)]"}
            >
              {l.text}
            </p>
          ))}
        </div>
      )}
      {bad.length > 0 && (
        <div role="alert" className="space-y-0.5 text-xs text-red-400">
          {bad.map((l, i) => (
            <p key={`${l.text}-${i}`}>{l.text}</p>
          ))}
        </div>
      )}
    </div>
  );
}

// ── confirm panel for needs_confirm ───────────────────────────────────────────

/** Inline replacement for a confirm dialog: focusable, testable, keeps the form visible. */
export const ConfirmPanel = forwardRef<
  HTMLDivElement,
  {
    needs: string[];
    busy?: boolean;
    titleId: string;
    onConfirm: () => void;
    onBack: () => void;
  }
>(function ConfirmPanel({ needs, busy, titleId, onConfirm, onBack }, ref) {
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="group"
      aria-labelledby={titleId}
      className="rounded-md border border-amber-400/40 bg-amber-500/5 p-3 space-y-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)]"
    >
      <p id={titleId} className="text-sm font-semibold text-amber-400">
        Check before saving
      </p>
      <ul className="space-y-1 text-sm">
        {needs.map((code) => (
          <li key={code}>{needsText(code)}</li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button type="button" size="sm" onClick={onConfirm} disabled={busy}>
          Confirm and save
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onBack} disabled={busy}>
          Go back
        </Button>
      </div>
    </div>
  );
});
