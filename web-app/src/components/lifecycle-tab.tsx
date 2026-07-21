"use client";

import { useEffect, useState } from "react";
import { api, type KeySummary, type LifecycleResp } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

function maskValue(v: string): string {
  if (!v || v.length <= 4) return "****";
  return v.slice(0, 4) + "*****";
}

function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return d;
  }
}

function statusColor(status: string): string {
  if (status === "healthy") return "text-emerald-400";
  if (status === "warning") return "text-orange-400";
  if (status === "critical" || status === "overdue") return "text-red-400";
  return "text-[var(--color-muted-foreground)]";
}

function envVariant(env: string) {
  if (env === "prod") return "destructive" as const;
  if (env === "staging") return "warning" as const;
  if (env === "dev") return "success" as const;
  return "secondary" as const;
}

function ProgressBar({ age, interval }: { age: number | null; interval: number }) {
  if (age === null || interval <= 0) return null;
  const pct = Math.min(100, Math.round((age / interval) * 100));
  const color =
    pct >= 90 ? "bg-red-400" :
    pct >= 65 ? "bg-orange-400" :
    "bg-emerald-400";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-[var(--color-muted-foreground)]">
        <span>Age progress</span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-white/10 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="flex justify-between text-xs text-[var(--color-muted-foreground)]">
        <span>{age} days old</span>
        <span>{interval} day cycle</span>
      </div>
    </div>
  );
}

function InfoRow({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start gap-2 min-w-0">
      <span className="shrink-0 w-36 text-xs text-[var(--color-muted-foreground)]">{label}</span>
      <span className={`text-xs text-[var(--color-foreground)] truncate ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

export function LifecycleTab() {
  const [keys, setKeys] = useState<KeySummary[]>([]);
  const [keysLoading, setKeysLoading] = useState(true);
  const [keysErr, setKeysErr] = useState<string | null>(null);

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<LifecycleResp | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailErr, setDetailErr] = useState<string | null>(null);

  useEffect(() => {
    setKeysLoading(true);
    setKeysErr(null);
    api.listKeys()
      .then((r) => setKeys(r.keys))
      .catch((e) => setKeysErr(e instanceof Error ? e.message : "load failed"))
      .finally(() => setKeysLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedKey) { setDetail(null); return; }
    setDetailLoading(true);
    setDetailErr(null);
    setDetail(null);
    api.getLifecycle(selectedKey)
      .then(setDetail)
      .catch((e) => setDetailErr(e instanceof Error ? e.message : "load failed"))
      .finally(() => setDetailLoading(false));
  }, [selectedKey]);

  return (
    <div className="flex h-full gap-4" style={{ minHeight: "calc(100vh - 10rem)" }}>
      {/* Sidebar */}
      <div className="w-56 shrink-0 rounded-md border bg-[var(--color-card)] overflow-y-auto">
        <div className="px-3 py-2 border-b">
          <span className="text-xs font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider">Keys</span>
        </div>
        {keysLoading && (
          <p className="p-3 text-xs text-[var(--color-muted-foreground)]">Loading…</p>
        )}
        {keysErr && (
          <p className="p-3 text-xs text-red-400">{keysErr}</p>
        )}
        {!keysLoading && keys.length === 0 && !keysErr && (
          <p className="p-3 text-xs text-[var(--color-muted-foreground)]">No keys found.</p>
        )}
        <ul>
          {keys.map((k) => (
            <li key={k.name}>
              <button
                onClick={() => setSelectedKey(k.name)}
                className={`w-full text-left px-3 py-2 text-xs font-mono truncate transition-colors hover:bg-white/5 ${
                  selectedKey === k.name
                    ? "bg-cyan-400/10 text-cyan-400 border-l-2 border-cyan-400"
                    : "text-[var(--color-foreground)]"
                }`}
              >
                {k.name}
              </button>
            </li>
          ))}
        </ul>
      </div>

      {/* Detail panel */}
      <div className="flex-1 min-w-0 rounded-md border bg-[var(--color-card)] overflow-y-auto">
        {!selectedKey && (
          <div className="flex h-full items-center justify-center text-sm text-[var(--color-muted-foreground)]">
            Select a key to view its lifecycle
          </div>
        )}

        {selectedKey && detailLoading && (
          <div className="flex h-full items-center justify-center text-sm text-[var(--color-muted-foreground)]">
            Loading…
          </div>
        )}

        {selectedKey && detailErr && (
          <div className="p-6 text-sm text-red-400">{detailErr}</div>
        )}

        {detail && !detailLoading && (
          <div className="p-6 space-y-6">
            {/* Header */}
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-mono text-lg font-semibold text-cyan-400 mr-2">{detail.name}</h2>
              <Badge variant={envVariant(detail.env)}>{detail.env}</Badge>
              <span className={`text-xs font-semibold uppercase ${statusColor(detail.status)}`}>
                {detail.status}
              </span>
            </div>

            {/* Info grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-y-2 gap-x-6">
              <InfoRow label="Provider" value={detail.provider || "—"} />
              <InfoRow label="Created" value={fmtDate(detail.created)} />
              <InfoRow label="Last rotated" value={fmtDate(detail.rotated)} />
              <InfoRow label="Age (days)" value={detail.age_days !== null ? String(detail.age_days) : "—"} />
              <InfoRow label="Next due" value={fmtDate(detail.next_due_date)} />
              <InfoRow label="Rotation interval" value={`${detail.rotation_interval_days} days`} />
            </div>

            {/* Progress */}
            <ProgressBar age={detail.age_days} interval={detail.rotation_interval_days} />

            {/* Dual rotation */}
            {detail.dual_rotation && (
              <div className="rounded-md border border-cyan-400/20 bg-cyan-400/5 p-4 space-y-1">
                <p className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">Dual Rotation</p>
                {detail.next_value_present ? (
                  <p className="text-xs text-[var(--color-foreground)]">
                    Backup staged — added {fmtDate(detail.next_added)}
                  </p>
                ) : (
                  <p className="text-xs text-orange-400">No backup staged yet.</p>
                )}
              </div>
            )}

            {/* Rotation history */}
            {detail.history && detail.history.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider">Rotation History</p>
                <div className="rounded-md border overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Retired</TableHead>
                        <TableHead>Value (masked)</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.history.map((h, i) => (
                        <TableRow key={i}>
                          <TableCell className="text-xs">{fmtDate(h.retired)}</TableCell>
                          <TableCell className="font-mono text-xs">{maskValue(h.value)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}

            {/* Projects */}
            {detail.projects && detail.projects.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-[var(--color-muted-foreground)] uppercase tracking-wider">Assigned Projects</p>
                <ul className="space-y-1">
                  {detail.projects.map((p) => (
                    <li key={p} className="text-xs font-mono text-[var(--color-foreground)] bg-white/5 px-2 py-1 rounded">
                      {p}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
