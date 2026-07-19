"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { CheckCircle, AlertCircle, Info, AlertTriangle, X } from "lucide-react";

export type ToastVariant = "success" | "error" | "info" | "warning";

export interface ToastItem {
  id: string;
  message: string;
  variant: ToastVariant;
}

interface ToastCtx {
  push: (variant: ToastVariant, message: string) => void;
  dismiss: (id: string) => void;
  items: ToastItem[];
}

const Ctx = createContext<ToastCtx | null>(null);

// Module-level dispatcher so a non-hook `toast()` API can fire from anywhere.
let dispatcher: ((variant: ToastVariant, message: string) => void) | null = null;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setItems((p) => p.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((variant: ToastVariant, message: string) => {
    const id = Math.random().toString(36).slice(2, 9);
    setItems((p) => [...p, { id, message, variant }]);
    setTimeout(() => {
      setItems((p) => p.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  useEffect(() => {
    dispatcher = push;
    return () => { dispatcher = null; };
  }, [push]);

  return <Ctx.Provider value={{ push, dismiss, items }}>{children}</Ctx.Provider>;
}

export function useToast() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useToast must be used inside ToastProvider");
  return c;
}

const variantStyles: Record<ToastVariant, { border: string; text: string; Icon: typeof CheckCircle }> = {
  success: { border: "border-emerald-400/40 bg-emerald-400/5", text: "text-emerald-400", Icon: CheckCircle },
  error:   { border: "border-red-500/40 bg-red-500/5",         text: "text-red-400",     Icon: AlertCircle },
  info:    { border: "border-cyan-400/40 bg-cyan-400/5",       text: "text-cyan-400",    Icon: Info },
  warning: { border: "border-orange-400/40 bg-orange-400/5",   text: "text-orange-400",  Icon: AlertTriangle },
};

export function ToastViewport() {
  const ctx = useContext(Ctx);
  if (!ctx) return null;
  const { items, dismiss } = ctx;
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2">
      {items.map((t) => {
        const { border, text, Icon } = variantStyles[t.variant];
        return (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-2 rounded-md border ${border} bg-[var(--color-card)] p-3 text-sm shadow-lg animate-in slide-in-from-right-4 fade-in`}
            style={{ animation: "toast-in 220ms ease-out" }}
          >
            <Icon className={`h-4 w-4 shrink-0 mt-0.5 ${text}`} />
            <p className="flex-1 text-[var(--color-foreground)] break-words">{t.message}</p>
            <button
              onClick={() => dismiss(t.id)}
              className="text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] transition-colors"
              aria-label="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
      <style jsx global>{`
        @keyframes toast-in {
          from { opacity: 0; transform: translateX(20px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  );
}

function fire(variant: ToastVariant, message: string) {
  if (dispatcher) dispatcher(variant, message);
  else if (typeof window !== "undefined") console.warn("[toast] no provider mounted:", message);
}

export const toast = {
  success: (msg: string) => fire("success", msg),
  error:   (msg: string) => fire("error", msg),
  info:    (msg: string) => fire("info", msg),
  warning: (msg: string) => fire("warning", msg),
};
