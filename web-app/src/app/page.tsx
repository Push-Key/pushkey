"use client";

import { useEffect, useState } from "react";
import { Sidebar, type Tab } from "@/components/sidebar";
import { LoginScreen } from "@/components/login-screen";
import { DashboardTab } from "@/components/dashboard-tab";
import { VaultTab } from "@/components/vault-tab";
import { ProjectsTab } from "@/components/projects-tab";
import { HealthTab } from "@/components/health-tab";
import { ForecastTab } from "@/components/forecast-tab";
import { LifecycleTab } from "@/components/lifecycle-tab";
import { AuditTab } from "@/components/audit-tab";
import { AgentsTab } from "@/components/agents-tab";
import { SettingsTab } from "@/components/settings-tab";
import { api, type StatusResp } from "@/lib/api";
import { bootstrapSession } from "@/lib/auth";

export default function Page() {
  const [status, setStatus] = useState<StatusResp | null>(null);
  const [tab, setTab] = useState<Tab>("dashboard");
  const [tokenReady, setTokenReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    bootstrapSession()
      .catch(() => null)
      .finally(() => setTokenReady(true));
  }, []);

  const refreshStatus = async () => {
    try {
      const s = await api.status();
      setStatus(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "status failed");
      setStatus(null);
    }
  };

  useEffect(() => {
    if (!tokenReady) return;
    refreshStatus();
    const id = setInterval(refreshStatus, 30_000);
    return () => clearInterval(id);
  }, [tokenReady]);

  const lock = async () => {
    await api.lock();
    refreshStatus();
  };

  if (!tokenReady) return null;

  if (error && !status) {
    return (
      <div className="flex h-screen items-center justify-center p-4">
        <div className="max-w-md rounded-lg border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/10 p-6 text-sm">
          <div className="font-semibold text-[var(--color-destructive)]">Cannot reach Pushkey local API</div>
          <p className="mt-2 text-[var(--color-muted-foreground)]">{error}</p>
          <p className="mt-4 text-xs text-[var(--color-muted-foreground)]">
            Make sure you opened this app via <code className="text-[var(--color-foreground)]">pushkey app</code> from the CLI — opening this URL directly bypasses the launch token.
          </p>
        </div>
      </div>
    );
  }

  if (!status) return null;

  if (status.locked) {
    return <LoginScreen hasVault={status.has_vault} onUnlocked={refreshStatus} />;
  }

  return (
    <div className="flex h-screen">
      <Sidebar active={tab} onSelect={setTab} onLock={lock} keyCount={status.key_count} />
      <main className="flex-1 overflow-auto p-6">
        {tab === "dashboard" && <DashboardTab onNavigate={(t) => setTab(t as Tab)} />}
        {tab === "vault"     && <VaultTab />}
        {tab === "projects"  && <ProjectsTab />}
        {tab === "health"    && <HealthTab />}
        {tab === "forecast"  && <ForecastTab />}
        {tab === "lifecycle" && <LifecycleTab />}
        {tab === "audit"     && <AuditTab />}
        {tab === "agents"    && <AgentsTab />}
        {tab === "settings"  && <SettingsTab onLock={lock} />}
      </main>
    </div>
  );
}
