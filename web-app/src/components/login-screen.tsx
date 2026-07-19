"use client";

import { useEffect, useState } from "react";
import { Loader2, Lock, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";

interface Props {
  hasVault: boolean;
  onUnlocked: () => void;
}

function formatRecovery(raw: string) {
  const cleaned = raw.toUpperCase().replace(/[^A-Z0-9]/g, "");
  const body = cleaned.startsWith("PUSH") ? cleaned.slice(4) : cleaned;
  const groups = body.match(/.{1,4}/g)?.slice(0, 4) ?? [];
  return ["PUSH", ...groups].filter(Boolean).join("-");
}

export function LoginScreen({ hasVault, onUnlocked }: Props) {
  const [mode, setMode] = useState<"password" | "recovery">("password");
  const [password, setPassword] = useState("");
  const [recovery, setRecovery] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [shake, setShake] = useState(false);
  const [since] = useState(() => new Date());

  useEffect(() => {
    if (!err) return;
    setShake(true);
    const t = setTimeout(() => setShake(false), 500);
    return () => clearTimeout(t);
  }, [err]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      if (mode === "password") await api.unlock({ password });
      else await api.unlock({ recovery_code: recovery });
      onUnlocked();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "unknown error");
    } finally {
      setBusy(false);
    }
  };

  const pillCls = (active: boolean) =>
    `flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
      active
        ? "bg-cyan-400/10 text-cyan-400 border border-cyan-400/30"
        : "text-[var(--color-muted-foreground)] border border-transparent hover:text-[var(--color-foreground)]"
    }`;

  return (
    <div
      className="flex min-h-screen items-center justify-center p-4"
      style={{
        background:
          "radial-gradient(ellipse at 50% 30%, rgba(0,217,255,0.05) 0%, transparent 60%), var(--color-background)",
      }}
    >
      <div
        className={`w-full max-w-md rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] p-7 shadow-2xl ${
          shake ? "animate-[shake_0.45s_cubic-bezier(.36,.07,.19,.97)]" : ""
        }`}
      >
        <div className="flex flex-col items-center text-center mb-6">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.png" alt="Pushkey" className="h-20 w-20 mb-3 drop-shadow-[0_0_20px_rgba(0,217,255,0.15)]" />
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-foreground)]">Pushkey</h1>
          <p className="text-xs text-[var(--color-muted-foreground)] mt-1">Your encrypted API key vault</p>
        </div>

        {!hasVault ? (
          <div className="rounded-md border border-orange-400/30 bg-orange-400/5 p-4 text-center space-y-2">
            <ShieldAlert className="h-5 w-5 text-orange-400 mx-auto" />
            <p className="text-sm text-[var(--color-foreground)] font-medium">No vault found</p>
            <p className="text-xs text-[var(--color-muted-foreground)]">
              Use the desktop app or run <code className="font-mono text-cyan-400">pushkey init</code> to create one.
            </p>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div className="flex gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] p-1">
              <button type="button" onClick={() => { setMode("password"); setErr(null); }} className={pillCls(mode === "password")}>
                Master Password
              </button>
              <button type="button" onClick={() => { setMode("recovery"); setErr(null); }} className={pillCls(mode === "recovery")}>
                Recovery Code
              </button>
            </div>

            {mode === "password" ? (
              <div className="space-y-1.5">
                <Label htmlFor="pw" className="text-xs">Master password</Label>
                <Input
                  id="pw"
                  type="password"
                  autoFocus
                  placeholder="Enter your master password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={busy}
                />
              </div>
            ) : (
              <div className="space-y-1.5">
                <Label htmlFor="rec" className="text-xs">Recovery code</Label>
                <Input
                  id="rec"
                  autoFocus
                  placeholder="PUSH-XXXX-XXXX-XXXX-XXXX"
                  className="font-mono tracking-wider"
                  value={recovery}
                  onChange={(e) => setRecovery(formatRecovery(e.target.value))}
                  disabled={busy}
                />
                <p className="flex items-center gap-1.5 text-[11px] text-orange-400">
                  <ShieldAlert className="h-3 w-3" /> Recovery unlock is read-only
                </p>
              </div>
            )}

            {err && (
              <div className="rounded-md border border-red-500/40 bg-red-500/10 p-2.5 text-xs text-red-400">
                {err}
              </div>
            )}

            <Button
              type="submit"
              className="w-full bg-cyan-400/10 border border-cyan-400/30 text-cyan-400 hover:bg-cyan-400/20"
              disabled={busy || (mode === "password" ? !password : recovery.length < 8)}
            >
              {busy ? (
                <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Unlocking…</>
              ) : (
                <><Lock className="h-4 w-4 mr-2" /> {mode === "password" ? "Unlock" : "Recover"}</>
              )}
            </Button>
          </form>
        )}

        <div className="mt-6 pt-4 border-t border-[var(--color-border)] text-center">
          <p className="text-[10px] text-[var(--color-muted-foreground)]">
            Locked since {since.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </p>
        </div>
      </div>

      <style jsx global>{`
        @keyframes shake {
          10%, 90% { transform: translateX(-1px); }
          20%, 80% { transform: translateX(2px); }
          30%, 50%, 70% { transform: translateX(-4px); }
          40%, 60% { transform: translateX(4px); }
        }
      `}</style>
    </div>
  );
}
