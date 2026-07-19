"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Shield, Key, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, HealthEntry, HealthResp } from "@/lib/api";

function scoreColor(score: number): string {
  if (score >= 80) return "text-emerald-400";
  if (score >= 50) return "text-orange-400";
  return "text-red-400";
}

function statusBadge(status: HealthEntry["status"]) {
  if (status === "critical")
    return <Badge className="bg-red-400/20 text-red-400 border-red-400/30">Critical</Badge>;
  return <Badge className="bg-orange-400/20 text-orange-400 border-orange-400/30">Warning</Badge>;
}

function StaleTable({ entries }: { entries: HealthEntry[] }) {
  if (entries.length === 0)
    return <p className="text-sm py-3" style={{ color: "var(--color-muted-foreground)" }}>No stale keys.</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow style={{ borderColor: "var(--color-muted-foreground)" }}>
          <TableHead>Name</TableHead>
          <TableHead>Provider</TableHead>
          <TableHead>Env</TableHead>
          <TableHead>Age (days)</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((e) => (
          <TableRow key={e.name} style={{ borderColor: "var(--color-muted-foreground)" }}>
            <TableCell className="font-mono text-sm" style={{ color: "var(--color-foreground)" }}>{e.name}</TableCell>
            <TableCell className="text-sm" style={{ color: "var(--color-muted-foreground)" }}>{e.provider || "—"}</TableCell>
            <TableCell className="text-sm" style={{ color: "var(--color-muted-foreground)" }}>{e.env || "—"}</TableCell>
            <TableCell className="text-sm" style={{ color: "var(--color-foreground)" }}>{e.age_days}</TableCell>
            <TableCell>{statusBadge(e.status)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function HealthyTable({ entries }: { entries: HealthEntry[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-sm font-medium mb-2"
        style={{ color: "var(--color-muted-foreground)" }}
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        Healthy keys ({entries.length})
      </button>
      {open && (
        entries.length === 0 ? (
          <p className="text-sm pl-4" style={{ color: "var(--color-muted-foreground)" }}>No healthy keys.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow style={{ borderColor: "var(--color-muted-foreground)" }}>
                <TableHead>Name</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Env</TableHead>
                <TableHead>Age (days)</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((e) => (
                <TableRow key={e.name} style={{ borderColor: "var(--color-muted-foreground)" }}>
                  <TableCell className="font-mono text-sm" style={{ color: "var(--color-foreground)" }}>{e.name}</TableCell>
                  <TableCell className="text-sm" style={{ color: "var(--color-muted-foreground)" }}>{e.provider || "—"}</TableCell>
                  <TableCell className="text-sm" style={{ color: "var(--color-muted-foreground)" }}>{e.env || "—"}</TableCell>
                  <TableCell className="text-sm" style={{ color: "var(--color-foreground)" }}>{e.age_days}</TableCell>
                  <TableCell>
                    <Badge className="bg-emerald-400/20 text-emerald-400 border-emerald-400/30">Healthy</Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )
      )}
    </div>
  );
}

function PillList({ items, label }: { items: string[]; label: string }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--color-muted-foreground)" }}>
        {label}
      </p>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => (
          <span
            key={item}
            className="px-2 py-0.5 rounded-full text-xs font-mono bg-orange-400/10 text-orange-400 border border-orange-400/30"
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

export function HealthTab() {
  const [data, setData] = useState<HealthResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(90);
  const [pendingThreshold, setPendingThreshold] = useState(90);

  const fetch = useCallback(async (days: number) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getHealth(days);
      setData(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load health data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(threshold); }, [fetch, threshold]);

  const applyThreshold = () => {
    if (pendingThreshold !== threshold) setThreshold(pendingThreshold);
    else fetch(threshold);
  };

  return (
    <div className="space-y-6 p-4">
      {/* Threshold control */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium" style={{ color: "var(--color-muted-foreground)" }}>
          Staleness threshold:
        </label>
        <input
          type="number"
          min={1}
          max={730}
          value={pendingThreshold}
          onChange={(e) => setPendingThreshold(Number(e.target.value))}
          onKeyDown={(e) => e.key === "Enter" && applyThreshold()}
          className="w-20 rounded border px-2 py-1 text-sm bg-transparent"
          style={{
            borderColor: "var(--color-muted-foreground)",
            color: "var(--color-foreground)",
          }}
        />
        <span className="text-sm" style={{ color: "var(--color-muted-foreground)" }}>days</span>
        <Button size="sm" variant="outline" onClick={applyThreshold}>Apply</Button>
      </div>

      {loading && (
        <p className="text-sm" style={{ color: "var(--color-muted-foreground)" }}>Loading health data…</p>
      )}

      {error && (
        <div className="rounded-lg border border-red-400/30 bg-red-400/10 p-4">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      {!loading && !error && data && (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card style={{ background: "var(--color-card)" }}>
              <CardHeader className="pb-1">
                <CardTitle className="flex items-center gap-2 text-sm font-medium" style={{ color: "var(--color-muted-foreground)" }}>
                  <Shield size={14} /> Security Score
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className={`text-5xl font-bold tabular-nums ${scoreColor(data.score)}`}>
                  {data.score}
                </p>
                <p className="text-xs mt-1" style={{ color: "var(--color-muted-foreground)" }}>out of 100</p>
              </CardContent>
            </Card>

            <Card style={{ background: "var(--color-card)" }}>
              <CardHeader className="pb-1">
                <CardTitle className="flex items-center gap-2 text-sm font-medium" style={{ color: "var(--color-muted-foreground)" }}>
                  <Key size={14} /> Total Keys
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-5xl font-bold tabular-nums text-cyan-400">{data.total}</p>
                <p className="text-xs mt-1 text-emerald-400">{data.healthy.length} healthy</p>
              </CardContent>
            </Card>

            <Card style={{ background: "var(--color-card)" }}>
              <CardHeader className="pb-1">
                <CardTitle className="flex items-center gap-2 text-sm font-medium" style={{ color: "var(--color-muted-foreground)" }}>
                  <AlertTriangle size={14} /> Stale Keys
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className={`text-5xl font-bold tabular-nums ${data.stale.length > 0 ? "text-orange-400" : "text-emerald-400"}`}>
                  {data.stale.length}
                </p>
                <p className="text-xs mt-1" style={{ color: "var(--color-muted-foreground)" }}>
                  threshold: {data.threshold_days}d
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Stale keys table */}
          <div>
            <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--color-foreground)" }}>
              Stale / At-Risk Keys
            </h3>
            <StaleTable entries={data.stale} />
          </div>

          {/* Healthy keys (collapsed) */}
          <HealthyTable entries={data.healthy} />

          {/* Warning lists */}
          <div className="space-y-4">
            <PillList items={data.unknown_provider} label="Unknown Provider" />
            <PillList items={data.backup_missing} label="Backup Missing" />
          </div>
        </>
      )}
    </div>
  );
}
