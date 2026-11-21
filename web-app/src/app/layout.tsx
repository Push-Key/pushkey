import type { Metadata } from "next";
import "./globals.css";
import { ToastProvider, ToastViewport } from "@/lib/toast";

export const metadata: Metadata = {
  title: "Pushkey App",
  description: "Local vault dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:border focus:border-[var(--color-border)] focus:bg-[var(--color-card)] focus:px-3 focus:py-2 focus:text-sm"
        >
          Skip to main content
        </a>
        <ToastProvider>
          {children}
          <ToastViewport />
        </ToastProvider>
      </body>
    </html>
  );
}
