"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FolderOpen, Bot, Activity, AlertTriangle, ShieldAlert } from "lucide-react";
import { api, type HealthResp, type ForecastItem } from "@/lib/api";

type DashState = {
  health: HealthResp | null;
  forecast: ForecastItem[];
  keyCount: number;
  projectCount: number;
  agentCount: number;
  recentAuditCount: number;
  loading: boolean;
};

const initial: DashState = {
  health: null,
  forecast: [],
  keyCount: 0,
  projectCount: 0,
  agentCount: 0,
  recentAuditCount: 0,
  loading: true,
};

function scoreColor(score: number): string {
  if (score >= 80) return "text-emerald-400";
  if (score >= 50) return "text-orange-400";
  return "text-red-400";
}

function daysColor(d: number): string {
  if (d < 0) return "text-red-400";
  if (d <= 14) return "text-orange-400";
  return "text-emerald-400";
}

function StatCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs uppercase tracking-wide text-[var(--color-muted-foreground)]">{label}</div>
        <div className="mt-2">{children}</div>
      </CardContent>
    </Card>
  );
}

function SkeletonCard() {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="h-3 w-20 rounded bg-[var(--color-muted)]/50" />
        <div className="mt-3 h-8 w-16 rounded bg-[var(--color-muted)]/30" />
      </CardContent>
    </Card>
  );
}

export function DashboardTab({ onNavigate }: { onNavigate: (tab: string) => void }) {
  const [s, setS] = useState<DashState>(initial);

  const load = async () => {
    try {
      const [health, forecast, keys, projects, agents, audit] = await Promise.all([
        api.getHealth(),
        api.getForecast(30),
        api.listKeys(),
        api.listProjects(),
        api.listAgents(),
        api.getAudit(50),
      ]);
      const now = Date.now();
      const dayMs = 24 * 60 * 60 * 1000;
      let recent = 0;
      let parsable = 0;
      for (const e of audit.events) {
        if (e.timestamp) {
          const t = Date.parse(e.timestamp);
          if (!Number.isNaN(t)) {
            parsable++;
            if (now - t <= dayMs) recent++;
          }
        }
      }
      setS({
        health,
        forecast: forecast.upcoming,
        keyCount: keys.count,
        projectCount: projects.count,
        agentCount: agents.tokens.length,
        recentAuditCount: parsable > 0 ? recent : audit.count,
        loading: false,
      });
    } catch {
      setS((prev) => ({ ...prev, loading: false }));
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  if (s.loading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          <SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
      </div>
    );
  }

  const h = s.health;
  const score = h?.score ?? 0;
  const healthyCount = h?.healthy.length ?? 0;
  const staleCount = h?.stale.length ?? 0;
  const backupCount = (s.keyCount) - (h?.backup_missing.length ?? 0);
  const upcoming = [...s.forecast].sort((a, b) => a.days_left - b.days_left).slice(0, 5);
  const unknown = h?.unknown_provider ?? [];
  const missingBackup = h?.backup_missing ?? [];
  const noIssues = unknown.length === 0 && missingBackup.length === 0;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-[var(--color-foreground)]">Dashboard</h1>
        <p className="text-sm text-[var(--color-muted-foreground)]">Vault status at a glance</p>
      </div>

      {/* Top row — 4 stat cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <StatCard label="Security Score">
          <div className={`text-4xl font-bold ${scoreColor(score)}`}>{score}</div>
          <div className="mt-1 text-xs text-[var(--color-muted-foreground)]">/ 100</div>
        </StatCard>
        <StatCard label="Total Keys">
          <div className="text-4xl font-bold text-[var(--color-foreground)]">{s.keyCount}</div>
          <div className="mt-1 text-xs text-emerald-400">{healthyCount} healthy</div>
        </StatCard>
        <StatCard label="Need Rotation">
          <div className={`text-4xl font-bold ${staleCount > 0 ? "text-orange-400" : "text-emerald-400"}`}>
            {staleCount}
          </div>
          <div className="mt-1 text-xs text-[var(--color-muted-foreground)]">stale keys</div>
        </StatCard>
        <StatCard label="Backups Staged">
          <div className="text-4xl font-bold text-cyan-400">{Math.max(0, backupCount)}</div>
          <div className="mt-1 text-xs text-[var(--color-muted-foreground)]">of {s.keyCount} keys</div>
        </StatCard>
      </div>

      {/* Middle row — 2 panels */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Upcoming Rotations</CardTitle>
              <button
                onClick={() => onNavigate("forecast")}
                className="text-xs text-cyan-400 hover:underline"
              >
                View all →
              </button>
            </div>
            <p className="text-xs text-[var(--color-muted-foreground)]">Next 30 days</p>
          </CardHeader>
          <CardContent>
            {upcoming.length === 0 ? (
              <div className="py-6 text-center text-sm text-[var(--color-muted-foreground)]">
                No rotations due in the next 30 days
              </div>
            ) : (
              <ul className="space-y-2">
                {upcoming.map((it) => (
                  <li key={it.name} className="flex items-center justify-between text-sm">
                    <div className="flex flex-1 items-center gap-3 truncate">
                      <span className="font-mono text-cyan-400 truncate">{it.name}</span>
                      <span className="text-xs text-[var(--color-muted-foreground)] truncate">{it.provider}</span>
                    </div>
                    <span className={`text-xs font-medium ${daysColor(it.days_left)}`}>
                      {it.days_left < 0 ? `${Math.abs(it.days_left)}d overdue` : `${it.days_left}d`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Critical Issues</CardTitle>
            <p className="text-xs text-[var(--color-muted-foreground)]">Configuration & backup gaps</p>
          </CardHeader>
          <CardContent>
            {noIssues ? (
              <div className="py-6 text-center text-sm text-emerald-400">All systems normal</div>
            ) : (
              <ul className="space-y-2">
                {unknown.map((name) => (
                  <li key={`u-${name}`} className="flex items-center gap-3 text-sm">
                    <span className="h-2 w-2 shrink-0 rounded-full bg-orange-400" />
                    <span className="font-mono text-[var(--color-foreground)] truncate">{name}</span>
                    <span className="ml-auto text-xs text-[var(--color-muted-foreground)]">unknown provider</span>
                  </li>
                ))}
                {missingBackup.map((name) => (
                  <li key={`b-${name}`} className="flex items-center gap-3 text-sm">
                    <span className="h-2 w-2 shrink-0 rounded-full bg-red-400" />
                    <span className="font-mono text-[var(--color-foreground)] truncate">{name}</span>
                    <span className="ml-auto text-xs text-[var(--color-muted-foreground)]">backup missing</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Bottom row — Quick stats strip */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-3 p-4">
          <div className="flex items-center gap-2 text-sm">
            <FolderOpen className="h-4 w-4 text-cyan-400" />
            <span className="font-semibold text-[var(--color-foreground)]">{s.projectCount}</span>
            <span className="text-[var(--color-muted-foreground)]">projects</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Bot className="h-4 w-4 text-cyan-400" />
            <span className="font-semibold text-[var(--color-foreground)]">{s.agentCount}</span>
            <span className="text-[var(--color-muted-foreground)]">agent tokens</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Activity className="h-4 w-4 text-cyan-400" />
            <span className="font-semibold text-[var(--color-foreground)]">{s.recentAuditCount}</span>
            <span className="text-[var(--color-muted-foreground)]">recent events</span>
          </div>
          {(unknown.length > 0 || missingBackup.length > 0) && (
            <div className="flex items-center gap-2 text-sm ml-auto">
              {unknown.length > 0 && (
                <span className="flex items-center gap-1 text-orange-400">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {unknown.length}
                </span>
              )}
              {missingBackup.length > 0 && (
                <span className="flex items-center gap-1 text-red-400">
                  <ShieldAlert className="h-3.5 w-3.5" />
                  {missingBackup.length}
                </span>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
