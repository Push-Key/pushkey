"use client";

import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Key,
  FolderOpen,
  CalendarClock,
  Activity,
  LineChart,
  Bot,
  Settings,
  Lock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

export type Tab =
  | "dashboard"
  | "vault"
  | "projects"
  | "forecast"
  | "lifecycle"
  | "audit"
  | "health"
  | "agents"
  | "settings";

const items: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "vault",     label: "Vault",     icon: Key },
  { id: "projects",  label: "Projects",  icon: FolderOpen },
  { id: "forecast",  label: "Forecast",  icon: CalendarClock },
  { id: "lifecycle", label: "Lifecycle", icon: Activity },
  { id: "audit",     label: "Audit",     icon: Activity },
  { id: "health",    label: "Health",    icon: LineChart },
  { id: "agents",    label: "Agents",    icon: Bot },
  { id: "settings",  label: "Settings",  icon: Settings },
];

interface SidebarProps {
  active: Tab;
  onSelect: (tab: Tab) => void;
  onLock: () => void;
  keyCount: number;
}

export function Sidebar({ active, onSelect, onLock, keyCount }: SidebarProps) {
  const [staleCount, setStaleCount] = useState(0);
  const [overdueCount, setOverdueCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [h, f] = await Promise.all([
          api.getHealth(),
          api.getForecast(30).catch(() => ({ upcoming: [], count: 0, window_days: 30 })),
        ]);
        if (cancelled) return;
        setStaleCount(h.stale.length);
        setOverdueCount(f.upcoming.filter((u) => u.overdue).length);
      } catch {
        /* ignore */
      }
    };
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const renderBadge = (id: Tab) => {
    if (id === "health" && staleCount > 0) {
      return (
        <span className="ml-auto inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-[var(--color-destructive)] px-1.5 text-[10px] font-semibold text-white">
          {staleCount}
        </span>
      );
    }
    if (id === "forecast" && overdueCount > 0) {
      return (
        <span className="ml-auto inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-orange-500 px-1.5 text-[10px] font-semibold text-white">
          {overdueCount}
        </span>
      );
    }
    return null;
  };

  return (
    <aside className="flex w-full md:w-56 shrink-0 flex-col border-b bg-[var(--color-card)] md:h-screen md:border-b-0 md:border-r">
      <div className="flex items-center gap-2 px-4 py-4">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo.png" alt="Pushkey" className="h-8 w-8 shrink-0" />
        <div className="leading-tight">
          <div className="text-sm font-semibold">Pushkey</div>
          <div className="text-xs text-[var(--color-muted-foreground)]">{keyCount} keys</div>
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-2" aria-label="Primary navigation">
        {items.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            aria-current={active === id ? "page" : undefined}
            aria-label={`Open ${label}`}
            onClick={() => onSelect(id)}
            className={cn(
              "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
              active === id
                ? "bg-[var(--color-primary)]/10 text-[var(--color-primary)]"
                : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)] hover:text-[var(--color-foreground)]"
            )}
          >
            <Icon className="h-4 w-4" />
            <span>{label}</span>
            {renderBadge(id)}
          </button>
        ))}
      </nav>

      <div className="border-t p-3 space-y-2">
        <button
          type="button"
          aria-label="Lock vault"
          onClick={onLock}
          className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)] hover:text-[var(--color-destructive)]"
        >
          <Lock className="h-4 w-4" /> Lock vault
        </button>
        <div className="flex items-center justify-between px-3 text-[10px] text-[var(--color-muted-foreground)]/70">
          <span>v0.1.0</span>
          <button
            type="button"
            aria-label="Open Settings"
            onClick={() => onSelect("settings")}
            className="hover:text-[var(--color-foreground)] hover:underline"
          >
            Settings
          </button>
        </div>
      </div>
    </aside>
  );
}
