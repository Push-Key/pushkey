"use client";

import { Key, FolderOpen, CalendarClock, Activity, LineChart, Bot, Settings, Lock } from "lucide-react";
import { cn } from "@/lib/utils";

export type Tab =
  | "vault"
  | "projects"
  | "forecast"
  | "lifecycle"
  | "audit"
  | "health"
  | "agents"
  | "settings";

const items: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
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
  return (
    <aside className="flex h-screen w-56 shrink-0 flex-col border-r bg-[var(--color-card)]">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[var(--color-primary)] text-[var(--color-primary-foreground)] font-bold">P</div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">Pushkey</div>
          <div className="text-xs text-[var(--color-muted-foreground)]">{keyCount} keys</div>
        </div>
      </div>

      <nav className="flex-1 space-y-1 px-2">
        {items.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => onSelect(id)}
            className={cn(
              "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
              active === id
                ? "bg-[var(--color-primary)]/10 text-[var(--color-primary)]"
                : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)] hover:text-[var(--color-foreground)]"
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </nav>

      <div className="border-t p-3">
        <button
          onClick={onLock}
          className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)] hover:text-[var(--color-destructive)]"
        >
          <Lock className="h-4 w-4" /> Lock vault
        </button>
      </div>
    </aside>
  );
}
