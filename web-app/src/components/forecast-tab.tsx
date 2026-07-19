"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarClock, AlertCircle, ShieldCheck } from "lucide-react";
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
import { api, ForecastItem } from "@/lib/api";

const WINDOWS = [30, 60, 90, 180] as const;

function daysLeftColor(item: ForecastItem): string {
  if (item.overdue) return "text-red-400";
  if (item.days_left <= 14) return "text-orange-400";
  return "text-emerald-400";
}

function daysLeftLabel(item: ForecastItem): string {
  if (item.overdue) return `${Math.abs(item.days_left)}d overdue`;
  if (item.days_left === 0) return "Due today";
  return `${item.days_left}d`;
}

export function ForecastTab() {
  const [data, setData] = useState<{ upcoming: ForecastItem[]; count: number; window_days: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [window, setWindow] = useState<number>(90);

  const fetch = useCallback(async (days: number) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getForecast(days);
      setData(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load forecast data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(window); }, [fetch, window]);

  const handleWindow = (days: number) => {
    setWindow(days);
  };

  const overdueCount = data?.upcoming.filter((i) => i.overdue).length ?? 0;
  const withBackup = data?.upcoming.filter((i) => i.has_backup).length ?? 0;

  return (
    <div className="space-y-6 p-4">
      {/* Window selector */}
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium" style={{ color: "var(--color-muted-foreground)" }}>Window:</span>
        {WINDOWS.map((w) => (
          <Button
            key={w}
            size="sm"
            variant={window === w ? "default" : "outline"}
            onClick={() => handleWindow(w)}
            className={window === w ? "bg-cyan-400/20 text-cyan-400 border-cyan-400/40 hover:bg-cyan-400/30" : ""}
          >
            {w}d
          </Button>
        ))}
      </div>

      {loading && (
        <p className="text-sm" style={{ color: "var(--color-muted-foreground)" }}>Loading forecast…</p>
      )}

      {error && (
        <div className="rounded-lg border border-red-400/30 bg-red-400/10 p-4">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      {!loading && !error && data && (
        <>
          {/* Summary strip */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card style={{ background: "var(--color-card)" }}>
              <CardHeader className="pb-1">
                <CardTitle className="flex items-center gap-2 text-sm font-medium" style={{ color: "var(--color-muted-foreground)" }}>
                  <CalendarClock size={14} /> Upcoming Rotations
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-5xl font-bold tabular-nums text-cyan-400">{data.count}</p>
                <p className="text-xs mt-1" style={{ color: "var(--color-muted-foreground)" }}>
                  in next {data.window_days} days
                </p>
              </CardContent>
            </Card>

            <Card style={{ background: "var(--color-card)" }}>
              <CardHeader className="pb-1">
                <CardTitle className="flex items-center gap-2 text-sm font-medium" style={{ color: "var(--color-muted-foreground)" }}>
                  <AlertCircle size={14} /> Overdue
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className={`text-5xl font-bold tabular-nums ${overdueCount > 0 ? "text-red-400" : "text-emerald-400"}`}>
                  {overdueCount}
                </p>
                <p className="text-xs mt-1" style={{ color: "var(--color-muted-foreground)" }}>need immediate rotation</p>
              </CardContent>
            </Card>

            <Card style={{ background: "var(--color-card)" }}>
              <CardHeader className="pb-1">
                <CardTitle className="flex items-center gap-2 text-sm font-medium" style={{ color: "var(--color-muted-foreground)" }}>
                  <ShieldCheck size={14} /> Backup Staged
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-5xl font-bold tabular-nums text-emerald-400">{withBackup}</p>
                <p className="text-xs mt-1" style={{ color: "var(--color-muted-foreground)" }}>keys ready to promote</p>
              </CardContent>
            </Card>
          </div>

          {/* Forecast table */}
          {data.upcoming.length === 0 ? (
            <p className="text-sm py-4" style={{ color: "var(--color-muted-foreground)" }}>
              No rotations due in the next {data.window_days} days.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow style={{ borderColor: "var(--color-muted-foreground)" }}>
                  <TableHead>Key</TableHead>
                  <TableHead>Provider</TableHead>
                  <TableHead>Env</TableHead>
                  <TableHead>Due Date</TableHead>
                  <TableHead>Days Left</TableHead>
                  <TableHead>Backup</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.upcoming.map((item) => (
                  <TableRow
                    key={item.name}
                    style={{
                      borderColor: "var(--color-muted-foreground)",
                      ...(item.overdue
                        ? { borderLeft: "3px solid rgb(248 113 113)", paddingLeft: "0" }
                        : {}),
                    }}
                  >
                    <TableCell className="font-mono text-sm" style={{ color: "var(--color-foreground)" }}>
                      {item.name}
                    </TableCell>
                    <TableCell className="text-sm" style={{ color: "var(--color-muted-foreground)" }}>
                      {item.provider || "—"}
                    </TableCell>
                    <TableCell className="text-sm" style={{ color: "var(--color-muted-foreground)" }}>
                      {item.env || "—"}
                    </TableCell>
                    <TableCell className="text-sm" style={{ color: "var(--color-foreground)" }}>
                      {item.due_date}
                    </TableCell>
                    <TableCell className={`text-sm font-semibold tabular-nums ${daysLeftColor(item)}`}>
                      {daysLeftLabel(item)}
                    </TableCell>
                    <TableCell>
                      {item.has_backup ? (
                        <Badge className="bg-emerald-400/20 text-emerald-400 border-emerald-400/30">Staged</Badge>
                      ) : (
                        <Badge className="bg-red-400/10 text-red-400 border-red-400/20">Missing</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </>
      )}
    </div>
  );
}
