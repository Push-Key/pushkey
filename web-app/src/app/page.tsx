"use client";

import { useEffect, useState } from "react";
import { Sidebar, type Tab } from "@/components/sidebar";
import { LoginScreen } from "@/components/login-screen";
import { VaultTab } from "@/components/vault-tab";
import { api, type StatusResp } from "@/lib/api";
import { captureTokenFromUrl } from "@/lib/auth";

export default function Page() {
  const [status, setStatus] = useState<StatusResp | null>(null);
  const [tab, setTab] = useState<Tab>("vault");
  const [tokenReady, setTokenReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    captureTokenFromUrl();
    setTokenReady(true);
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
        {tab === "vault" && <VaultTab />}
        {tab !== "vault" && (
          <div className="flex h-full items-center justify-center text-sm text-[var(--color-muted-foreground)]">
            <div className="rounded-md border bg-[var(--color-card)] px-6 py-4">
              <div className="font-medium capitalize">{tab}</div>
              <div className="mt-1 text-xs">Coming in a later phase.</div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
