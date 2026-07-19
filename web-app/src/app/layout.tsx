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
        <ToastProvider>
          {children}
          <ToastViewport />
        </ToastProvider>
      </body>
    </html>
  );
}
