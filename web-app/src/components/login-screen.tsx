"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api";

interface Props {
  hasVault: boolean;
  onUnlocked: () => void;
}

export function LoginScreen({ hasVault, onUnlocked }: Props) {
  const [mode, setMode] = useState<"password" | "recovery">("password");
  const [password, setPassword] = useState("");
  const [recovery, setRecovery] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      if (mode === "password") {
        await api.unlock({ password });
      } else {
        await api.unlock({ recovery_code: recovery });
      }
      onUnlocked();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "unknown error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-[var(--color-background)] p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-[var(--color-primary)] text-[var(--color-primary-foreground)] font-bold">
              P
            </div>
            <div>
              <CardTitle>Pushkey</CardTitle>
              <CardDescription>{hasVault ? "Unlock your vault" : "No vault detected — initialize one via the desktop app"}</CardDescription>
            </div>
          </div>
        </CardHeader>
        <form onSubmit={submit}>
          <CardContent className="space-y-4">
            <div className="flex gap-2 text-xs">
              <button
                type="button"
                onClick={() => setMode("password")}
                className={`rounded-md px-3 py-1 ${mode === "password" ? "bg-[var(--color-primary)]/10 text-[var(--color-primary)]" : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)]"}`}
              >
                Master password
              </button>
              <button
                type="button"
                onClick={() => setMode("recovery")}
                className={`rounded-md px-3 py-1 ${mode === "recovery" ? "bg-[var(--color-primary)]/10 text-[var(--color-primary)]" : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)]"}`}
              >
                Recovery code
              </button>
            </div>
            {mode === "password" ? (
              <div className="space-y-2">
                <Label htmlFor="pw">Master password</Label>
                <Input id="pw" type="password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} disabled={!hasVault || busy} />
              </div>
            ) : (
              <div className="space-y-2">
                <Label htmlFor="rec">Recovery code</Label>
                <Input id="rec" placeholder="PUSH-XXXX-XXXX-XXXX-XXXX" autoFocus value={recovery} onChange={(e) => setRecovery(e.target.value.toUpperCase())} disabled={!hasVault || busy} />
                <p className="text-xs text-[var(--color-muted-foreground)]">
                  Recovery unlocks read-only. Use rekey to set a new password.
                </p>
              </div>
            )}
            {err && <div className="rounded-md border border-[var(--color-destructive)]/30 bg-[var(--color-destructive)]/10 p-2 text-sm text-[var(--color-destructive)]">{err}</div>}
          </CardContent>
          <CardFooter>
            <Button type="submit" className="w-full" disabled={!hasVault || busy || (mode === "password" ? !password : !recovery)}>
              {busy ? "Unlocking…" : "Unlock"}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
