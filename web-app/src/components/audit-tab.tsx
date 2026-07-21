"use client";

import { useEffect, useState, useMemo, useRef, useCallback } from "react";
import { Search, RefreshCw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { api, type AuditEvent } from "@/lib/api";

const LIMIT_OPTIONS = [50, 100, 200, 500] as const;
type LimitOption = (typeof LIMIT_OPTIONS)[number];

function fmtTimestamp(ts: string | undefined): string {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString("en-US", {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    return ts;
  }
}

function EventRow({ event }: { event: AuditEvent }) {
  const hasStructured = event.timestamp || event.message;

  if (!hasStructured) {
    return (
      <div className="flex items-start gap-3 py-2 px-3 border-b border-white/5 last:border-0">
        <span className="font-mono text-xs text-[var(--color-muted-foreground)] shrink-0 w-44">—</span>
        <span className="text-xs text-[var(--color-foreground)] break-all">{event.raw ?? ""}</span>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3 py-2 px-3 border-b border-white/5 last:border-0">
      <span className="font-mono text-xs text-[var(--color-muted-foreground)] shrink-0 w-44">
        {fmtTimestamp(event.timestamp)}
      </span>
      <span className="text-xs text-[var(--color-foreground)] break-words min-w-0">{event.message ?? event.raw ?? ""}</span>
    </div>
  );
}

export function AuditTab() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [limit, setLimit] = useState<LimitOption>(200);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async (lim: number) => {
    setLoading(true);
    setErr(null);
    try {
      const r = await api.getAudit(lim);
      // newest first
      setEvents([...r.events].reverse());
    } catch (e) {
      setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(limit); }, [limit, load]);

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (autoRefresh) {
      intervalRef.current = setInterval(() => load(limit), 10_000);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [autoRefresh, limit, load]);

  const filtered = useMemo(() => {
    const f = filter.toLowerCase();
    if (!f) return events;
    return events.filter((e) => {
      const hay = `${e.timestamp ?? ""} ${e.message ?? ""} ${e.raw ?? ""}`.toLowerCase();
      return hay.includes(f);
    });
  }, [events, filter]);

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Audit Log</h1>
        <div className="flex flex-wrap items-center gap-2">
          {/* Search */}
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-[var(--color-muted-foreground)]" />
            <Input
              placeholder="Filter events…"
              className="pl-8 w-56"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>

          {/* Limit selector */}
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value) as LimitOption)}
            className="h-9 rounded-md border border-white/10 bg-[var(--color-card)] px-2 text-xs text-[var(--color-foreground)] focus:outline-none focus:ring-1 focus:ring-cyan-400"
          >
            {LIMIT_OPTIONS.map((n) => (
              <option key={n} value={n}>{n} events</option>
            ))}
          </select>

          {/* Auto-refresh toggle */}
          <Button
            variant={autoRefresh ? "default" : "outline"}
            size="sm"
            onClick={() => setAutoRefresh((v) => !v)}
            className={autoRefresh ? "border-cyan-400 text-cyan-400 bg-cyan-400/10 hover:bg-cyan-400/20" : ""}
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${autoRefresh ? "animate-spin" : ""}`} />
            {autoRefresh ? "Live" : "Auto"}
          </Button>

          {/* Manual refresh */}
          <Button variant="outline" size="sm" onClick={() => load(limit)} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </Button>
        </div>
      </div>

      {/* Error */}
      {err && (
        <div className="rounded-md border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/10 p-3 text-sm text-[var(--color-destructive)]">
          {err}
        </div>
      )}

      {/* Count */}
      {!loading && !err && (
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {filtered.length} event{filtered.length !== 1 ? "s" : ""}
          {filter ? ` matching "${filter}"` : ""}
          {autoRefresh ? " · auto-refreshing every 10s" : ""}
        </p>
      )}

      {/* Event list */}
      <div className="rounded-md border bg-[var(--color-card)] overflow-hidden">
        {loading && (
          <p className="py-10 text-center text-sm text-[var(--color-muted-foreground)]">Loading…</p>
        )}
        {!loading && filtered.length === 0 && (
          <p className="py-10 text-center text-sm text-[var(--color-muted-foreground)]">No audit events found</p>
        )}
        {!loading && filtered.length > 0 && (
          <div className="divide-y divide-white/5">
            {filtered.map((ev, i) => (
              <EventRow key={i} event={ev} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
