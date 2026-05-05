"use client";

const STORAGE_KEY = "pushkey:launch_token";

export function captureTokenFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  const url = new URL(window.location.href);
  const t = url.searchParams.get("t");
  if (t) {
    sessionStorage.setItem(STORAGE_KEY, t);
    url.searchParams.delete("t");
    window.history.replaceState({}, "", url.toString());
    return t;
  }
  return sessionStorage.getItem(STORAGE_KEY);
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(STORAGE_KEY);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(STORAGE_KEY);
}
