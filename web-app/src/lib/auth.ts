"use client";

const STORAGE_KEY = "pushkey:session";
let sessionToken: string | null = null;
let bootstrapPromise: Promise<string | null> | null = null;

export async function bootstrapSession(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  if (sessionToken) return sessionToken;
  sessionToken = sessionStorage.getItem(STORAGE_KEY);
  if (sessionToken) return sessionToken;
  if (bootstrapPromise) return bootstrapPromise;
  bootstrapPromise = (async () => {
    const url = new URL(window.location.href);
    const fragment = new URLSearchParams(url.hash.slice(1));
    const launchToken = fragment.get("t");
    if (!launchToken) return null;
    const response = await fetch("/api/bootstrap", {
      method: "POST",
      headers: { Authorization: `Bearer ${launchToken}` },
    });
    if (!response.ok) return null;
    const body = await response.json() as { token: string };
    sessionToken = body.token;
    sessionStorage.setItem(STORAGE_KEY, body.token);
    // Remove the launch credential only after a successful exchange.
    window.history.replaceState({}, "", `${url.pathname}${url.search}`);
    return sessionToken;
  })().finally(() => { bootstrapPromise = null; });
  return bootstrapPromise;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionToken ?? sessionStorage.getItem(STORAGE_KEY);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  sessionToken = null;
  sessionStorage.removeItem(STORAGE_KEY);
}
