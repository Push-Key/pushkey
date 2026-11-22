"use client";

import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, describeApiError, type ConnectNotice as Notice, type Project } from "@/lib/api";
import { projectLabel, samePath } from "@/components/connect-ui";

type NoticeRow = { path: string; name: string; count: number };
type NoticeView = {
  title: string;
  intro: string | null;
  rows: NoticeRow[];
  extras: { heading: string; items: string[] }[];
  footer: string;
};

/** Names only. Mirrors the desktop notice (same wording, same lists), never a value. */
export function connectNoticeView(notice: Notice | null, projects: Project[]): NoticeView | null {
  if (!notice) return null;
  const list = <T,>(value: T[] | undefined): T[] => (Array.isArray(value) ? value : []);
  const pair = (item: unknown) =>
    Array.isArray(item) ? item.map((part) => String(part)).join(" / ") : String(item);

  const rows = list(notice.every_key_projects).map((path) => {
    const found = projects.find((p) => samePath(p.path, String(path)));
    return {
      path: found?.path ?? String(path),
      name: projectLabel(String(path), projects),
      count: found ? found.keys.length : 0,
    };
  });

  const extras: NoticeView["extras"] = [];
  if (list(notice.env_skipped).length > 0) {
    extras.push({
      heading:
        "These keys were not connected because their environment did not match the project's (project / key):",
      items: list(notice.env_skipped).map(pair),
    });
  }
  if (list(notice.unusable).length > 0) {
    extras.push({
      heading: "These projects have no usable folder and were not moved:",
      items: list(notice.unusable).map(String),
    });
  }
  if (list(notice.unregistered).length > 0) {
    extras.push({
      heading: "These keys allow a folder that is not a registered project (key / folder):",
      items: list(notice.unregistered).map(pair),
    });
  }
  if (rows.length === 0 && extras.length === 0) return null;

  if (rows.length > 0) {
    const noneYet = rows.every((r) => r.count === 0);
    const tail = noneYet
      ? rows.length === 1
        ? "This one has none yet:"
        : rows.length === 2
          ? "These two have none yet:"
          : "These have none yet:"
      : "Check which keys each one gets:";
    return {
      title: `${rows.length} project${rows.length === 1 ? "" : "s"} used to get every key`,
      intro:
        "Before this update, a project with no keys picked received every key in your vault. " +
        "Now a project only gets the keys you connect to it. " +
        tail,
      rows,
      extras,
      footer:
        "Their .env files are not changed. This notice stays until you hide it, in the app, the web app and the CLI.",
    };
  }
  return {
    title: "Some projects need a look",
    intro: "Some things could not be carried over when your projects were updated.",
    rows,
    extras,
    footer:
      "No .env files were changed. This notice stays until you hide it, in the app, the web app and the CLI.",
  };
}

export function ConnectNotice({
  canWrite,
  onPickKeys,
}: {
  canWrite: boolean;
  onPickKeys: (path: string) => void;
}) {
  const [notice, setNotice] = useState<Notice | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  // "Later" hides the banner for this page load only. Nothing is stored and
  // nothing is sent: only "Hide this notice" dismisses it for good.
  const [later, setLater] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const titleId = useId();

  useEffect(() => {
    let live = true;
    api.getNotice()
      .then((r) => { if (live) setNotice(r?.notice ?? null); })
      .catch(() => { /* no notice is the normal case; a failed lookup must not block the app */ });
    api.listProjects()
      .then((r) => { if (live) setProjects(r.projects); })
      .catch(() => { /* names fall back to the folder name */ });
    return () => { live = false; };
  }, []);

  const view = connectNoticeView(notice, projects);
  if (!view || later) return null;

  const hide = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.dismissNotice();
      setNotice(null);
    } catch (e) {
      setErr(describeApiError(e, "Could not hide the notice"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      aria-labelledby={titleId}
      className="mb-4 space-y-3 rounded-lg border border-amber-500/50 bg-[var(--color-card)] p-4"
    >
      <h2 id={titleId} className="text-lg font-semibold">{view.title}</h2>
      {view.intro && <p className="text-sm text-[var(--color-foreground)]">{view.intro}</p>}

      {view.rows.length > 0 && (
        <ul className="divide-y divide-[var(--color-border)] border-y border-[var(--color-border)]">
          {view.rows.map((row) => (
            <li key={row.path} className="flex items-center justify-between gap-3 py-2">
              <span>
                <strong>{row.name}</strong>{" "}
                <span className="text-sm text-[var(--color-muted-foreground)]">
                  · {row.count} {row.count === 1 ? "key" : "keys"}
                </span>
              </span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                aria-label={`Pick keys for ${row.name}`}
                onClick={() => onPickKeys(row.path)}
              >
                Pick keys
              </Button>
            </li>
          ))}
        </ul>
      )}

      {view.extras.map((extra) => (
        <div key={extra.heading} className="space-y-1 text-sm">
          <p>{extra.heading}</p>
          <ul className="list-disc pl-5 font-mono text-xs text-[var(--color-muted-foreground)]">
            {extra.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ))}

      <p className="text-sm text-[var(--color-muted-foreground)]">{view.footer}</p>

      {err && (
        <p role="alert" className="text-sm text-red-400">
          {err}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={() => setLater(true)}>
          Later
        </Button>
        {canWrite && (
          <Button type="button" variant="outline" onClick={hide} disabled={busy}>
            Hide this notice
          </Button>
        )}
      </div>
    </section>
  );
}
