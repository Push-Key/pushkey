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

function StatePanel({
  title,
  detail,
  tone = "info",
}: {
  title: string;
  detail: React.ReactNode;
  tone?: "info" | "error";
}) {
  const role = tone === "error" ? "alert" : "status";
  const ariaLive = tone === "error" ? "assertive" : "polite";
  return (
    <section className="flex h-screen items-center justify-center p-4" role={role} aria-live={ariaLive}>
      <div className="max-w-md rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] p-6 text-sm">
        <div className="font-semibold text-[var(--color-foreground)]">{title}</div>
        <div className="mt-2 text-[var(--color-muted-foreground)]">{detail}</div>
      </div>
    </section>
  );
}

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

  if (!tokenReady) {
    return (
      <main aria-label="Vault workspace">
        <StatePanel
          title="Preparing secure local session"
          detail="Exchanging the one-time launch token for a browser session."
        />
      </main>
    );
  }

  if (error && !status) {
    if (error.startsWith("401:")) {
      return (
        <main id="main-content" aria-label="Vault workspace">
          <StatePanel
            title="Vault session ended"
            detail="The local browser session is locked or expired. Reopen the app from the Pushkey CLI to start a new secure session."
          />
        </main>
      );
    }

    return (
      <main id="main-content" aria-label="Vault workspace" className="flex h-screen items-center justify-center p-4">
        <div className="max-w-xl rounded-lg border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/10 p-6 text-sm">
          <div className="font-semibold text-[var(--color-destructive)]">Cannot reach Pushkey local API</div>
          <p className="mt-2 text-[var(--color-muted-foreground)]">{error}</p>
          <div className="mt-4 rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-4">
            <div className="font-medium text-[var(--color-foreground)]">How to reopen it</div>
            <ol className="mt-2 list-decimal space-y-2 pl-5 text-[var(--color-muted-foreground)]">
              <li>Run <code className="text-[var(--color-foreground)]">pushkey app</code> from the CLI to open a fresh local session.</li>
              <li>Do not open the bare local URL manually — the browser needs the one-time launch token added by Pushkey.</li>
              <li>If the browser tab is stale, close it and run <code className="text-[var(--color-foreground)]">pushkey app</code> again.</li>
            </ol>
          </div>
        </div>
      </main>
    );
  }

  if (!status) {
    return (
      <StatePanel
        title="Loading vault status"
        detail="Checking lock state, vault availability, and write permissions."
      />
    );
  }

  if (status.locked) {
    return (
      <main id="main-content" aria-label="Vault workspace" className="min-h-screen">
        <div className="border-b border-[var(--color-border)] bg-[var(--color-card)] px-4 py-2 text-xs text-[var(--color-muted-foreground)]">
          Offline or locked: unlock locally to load vault data and write changes.
        </div>
        <LoginScreen hasVault={status.has_vault} onUnlocked={refreshStatus} />
      </main>
    );
  }

  return (
    <div className="flex h-screen flex-col md:flex-row">
      <Sidebar active={tab} onSelect={setTab} onLock={lock} keyCount={status.key_count} />
      <main id="main-content" className="flex-1 overflow-auto p-4 md:p-6">
        {tab === "dashboard" && <DashboardTab onNavigate={(t) => setTab(t as Tab)} />}
        {tab === "vault" && <VaultTab />}
        {tab === "projects" && <ProjectsTab />}
        {tab === "health" && <HealthTab />}
        {tab === "forecast" && <ForecastTab />}
        {tab === "lifecycle" && <LifecycleTab />}
        {tab === "audit" && <AuditTab />}
        {tab === "agents" && <AgentsTab />}
        {tab === "settings" && <SettingsTab onLock={lock} />}
      </main>
    </div>
  );
}
