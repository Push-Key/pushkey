"use client";

import { useEffect, useRef, useState } from "react";
import {
  Download, Upload, Lock, HardDrive, KeyRound, ShieldCheck, Copy, Check, AlertTriangle, Clock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { toast } from "@/lib/toast";

interface SettingsTabProps {
  onLock: () => void;
}

export function SettingsTab({ onLock }: SettingsTabProps) {
  const [exportLoading, setExportLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Recovery code generation
  const [recoveryPwd, setRecoveryPwd] = useState("");
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null);
  const [recoveryLoading, setRecoveryLoading] = useState(false);
  const [recoveryErr, setRecoveryErr] = useState<string | null>(null);
  const [recoveryCopied, setRecoveryCopied] = useState(false);

  // Rekey
  const [rkCode, setRkCode] = useState("");
  const [rkNew, setRkNew] = useState("");
  const [rkConfirm, setRkConfirm] = useState("");
  const [rkLoading, setRkLoading] = useState(false);
  const [rkErr, setRkErr] = useState<string | null>(null);
  const [rkOk, setRkOk] = useState(false);

  // Auto-lock display
  const [autolockSeconds, setAutolockSeconds] = useState<number | null>(null);

  useEffect(() => {
    api.status().then((s) => setAutolockSeconds(s.autolock_seconds)).catch(() => {});
  }, []);

  const handleExport = async () => {
    setExportLoading(true);
    try {
      const { blob_b64 } = await api.exportBackup();
      const bytes = Uint8Array.from(atob(blob_b64), (c) => c.charCodeAt(0));
      const blob = new Blob([bytes], { type: "application/octet-stream" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const date = new Date().toISOString().slice(0, 10);
      a.href = url;
      a.download = `pushkey-backup-${date}.enc`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Backup exported");
    } catch (e) {
      console.error("export failed", e);
      toast.error(e instanceof Error ? e.message : "export failed");
    } finally {
      setExportLoading(false);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportLoading(true);
    setImportResult(null);
    try {
      const buf = await file.arrayBuffer();
      const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
      const { imported, bytes } = await api.importBackup(b64);
      setImportResult(
        imported
          ? { ok: true, msg: `Imported ${bytes.toLocaleString()} bytes.` }
          : { ok: false, msg: "Import returned false — vault unchanged." }
      );
      if (imported) toast.success("Backup imported");
      else toast.warning("Import returned false — vault unchanged");
    } catch (e) {
      setImportResult({ ok: false, msg: e instanceof Error ? e.message : "import failed" });
    } finally {
      setImportLoading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleGenerateRecovery = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!recoveryPwd) return;
    setRecoveryLoading(true);
    setRecoveryErr(null);
    setRecoveryCode(null);
    try {
      const { recovery_code } = await api.addRecovery(recoveryPwd);
      setRecoveryCode(recovery_code);
      setRecoveryPwd("");
    } catch (e) {
      setRecoveryErr(e instanceof Error ? e.message : "failed to generate recovery code");
    } finally {
      setRecoveryLoading(false);
    }
  };

  const copyRecovery = async () => {
    if (!recoveryCode) return;
    await navigator.clipboard.writeText(recoveryCode);
    setRecoveryCopied(true);
    setTimeout(() => setRecoveryCopied(false), 1500);
  };

  const handleRekey = async (e: React.FormEvent) => {
    e.preventDefault();
    setRkErr(null);
    setRkOk(false);
    if (rkNew.length < 8) {
      setRkErr("New password must be at least 8 characters.");
      return;
    }
    if (rkNew !== rkConfirm) {
      setRkErr("New password and confirmation do not match.");
      return;
    }
    if (!rkCode) {
      setRkErr("Recovery code is required.");
      return;
    }
    setRkLoading(true);
    try {
      await api.rekey(rkCode, rkNew);
      setRkOk(true);
      setRkCode("");
      setRkNew("");
      setRkConfirm("");
    } catch (e) {
      setRkErr(e instanceof Error ? e.message : "rekey failed");
    } finally {
      setRkLoading(false);
    }
  };

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>

      {/* Backup */}
      <Card className="bg-[var(--color-card)] border-[var(--color-muted-foreground)]/20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <HardDrive className="h-4 w-4 text-cyan-400" />
            Backup
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-2">
            <p className="text-sm text-[var(--color-muted-foreground)]">
              Export an encrypted snapshot of your vault to disk.
            </p>
            <div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleExport}
                disabled={exportLoading}
                className="gap-2"
              >
                <Download className="h-4 w-4" />
                {exportLoading ? "Exporting…" : "Export backup"}
              </Button>
            </div>
          </div>

          <div className="border-t border-[var(--color-muted-foreground)]/15 pt-4 flex flex-col gap-2">
            <p className="text-sm text-[var(--color-muted-foreground)]">
              Restore from a previously exported <code className="font-mono text-xs">.enc</code> file.
            </p>
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => fileRef.current?.click()}
                disabled={importLoading}
                className="gap-2"
              >
                <Upload className="h-4 w-4" />
                {importLoading ? "Importing…" : "Import backup"}
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept=".enc"
                className="hidden"
                onChange={handleImport}
              />
              {importResult && (
                <span
                  className={`text-sm ${importResult.ok ? "text-emerald-400" : "text-red-400"}`}
                >
                  {importResult.msg}
                </span>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Recovery code */}
      <Card className="bg-[var(--color-card)] border-[var(--color-muted-foreground)]/20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <KeyRound className="h-4 w-4 text-cyan-400" />
            Recovery code
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-[var(--color-muted-foreground)]">
            Generate a one-time recovery code that lets you reset your master password if you forget it.
          </p>
          {!recoveryCode && (
            <form onSubmit={handleGenerateRecovery} className="flex flex-col gap-2 max-w-sm">
              <Label htmlFor="rec-pwd" className="text-xs">Master password</Label>
              <Input
                id="rec-pwd"
                type="password"
                placeholder="Confirm your master password"
                value={recoveryPwd}
                onChange={(e) => setRecoveryPwd(e.target.value)}
                className="text-xs"
              />
              <div>
                <Button
                  type="submit"
                  size="sm"
                  className="gap-2"
                  disabled={!recoveryPwd || recoveryLoading}
                >
                  <KeyRound className="h-4 w-4" />
                  {recoveryLoading ? "Generating…" : "Generate recovery code"}
                </Button>
              </div>
              {recoveryErr && (
                <p className="text-xs text-red-400">{recoveryErr}</p>
              )}
            </form>
          )}
          {recoveryCode && (
            <div className="rounded-md border border-orange-500/40 bg-orange-500/5 p-3 space-y-2">
              <div className="flex items-center gap-2 text-xs text-orange-400 font-medium">
                <AlertTriangle className="h-4 w-4" />
                Save this — you&apos;ll need it if you forget your password. Won&apos;t be shown again.
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 font-mono text-sm bg-[var(--color-card)] border border-[var(--color-muted-foreground)]/20 rounded px-2 py-2 break-all select-all">
                  {recoveryCode}
                </code>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={copyRecovery}
                  className="gap-1 shrink-0"
                >
                  {recoveryCopied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
                  {recoveryCopied ? "Copied" : "Copy"}
                </Button>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="text-xs text-[var(--color-muted-foreground)]"
                onClick={() => setRecoveryCode(null)}
              >
                Dismiss
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Rekey (change master password) */}
      <Card className="bg-[var(--color-card)] border-[var(--color-muted-foreground)]/20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4 text-cyan-400" />
            Change master password
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleRekey} className="flex flex-col gap-3 max-w-sm">
            <p className="text-sm text-[var(--color-muted-foreground)]">
              Use a recovery code to set a new master password.
            </p>
            <div className="space-y-1">
              <Label htmlFor="rk-code" className="text-xs">Recovery code</Label>
              <Input
                id="rk-code"
                type="text"
                placeholder="paste recovery code"
                value={rkCode}
                onChange={(e) => setRkCode(e.target.value)}
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="rk-new" className="text-xs">New master password (min 8 chars)</Label>
              <Input
                id="rk-new"
                type="password"
                value={rkNew}
                onChange={(e) => setRkNew(e.target.value)}
                className="text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="rk-confirm" className="text-xs">Confirm new password</Label>
              <Input
                id="rk-confirm"
                type="password"
                value={rkConfirm}
                onChange={(e) => setRkConfirm(e.target.value)}
                className="text-xs"
              />
            </div>
            <div>
              <Button
                type="submit"
                size="sm"
                className="gap-2"
                disabled={rkLoading || !rkCode || !rkNew || !rkConfirm}
              >
                <ShieldCheck className="h-4 w-4" />
                {rkLoading ? "Rekeying…" : "Change master password"}
              </Button>
            </div>
            {rkErr && <p className="text-xs text-red-400">{rkErr}</p>}
            {rkOk && (
              <p className="text-xs text-emerald-400">
                Master password changed. Use the new password next time you unlock.
              </p>
            )}
          </form>
        </CardContent>
      </Card>

      {/* Vault info */}
      <Card className="bg-[var(--color-card)] border-[var(--color-muted-foreground)]/20">
        <CardHeader>
          <CardTitle className="text-base">Vault info</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-[var(--color-muted-foreground)]">Location</span>
            <code className="font-mono text-xs text-[var(--color-foreground)]">~/.pushkey/vault.enc</code>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--color-muted-foreground)]">Schema</span>
            <span className="text-[var(--color-foreground)]">v1 — AES-256-GCM, Argon2id KDF</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-[var(--color-muted-foreground)] flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" /> Auto-lock
            </span>
            <span className="text-[var(--color-foreground)]">
              {autolockSeconds === null
                ? "—"
                : `After ${Math.round(autolockSeconds / 60)} minutes of idle`}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Danger zone */}
      <Card className="border border-red-500/40 bg-[var(--color-card)]">
        <CardHeader>
          <CardTitle className="text-base text-red-400">Danger zone</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-[var(--color-muted-foreground)]">
            Locking the vault clears the in-memory key and closes the local API server. You will need to re-enter your passphrase to continue.
          </p>
          <Button
            variant="destructive"
            size="sm"
            onClick={onLock}
            className="gap-2"
          >
            <Lock className="h-4 w-4" />
            Lock vault
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
