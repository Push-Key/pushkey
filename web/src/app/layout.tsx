import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import { RootProvider } from "fumadocs-ui/provider/next"
import "./globals.css"

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
})

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
})

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://push-key.com"),
  title: "PushKey — Encrypted API Key Vault",
  description: "Store, rotate, and inject your API secrets into every project automatically. AES-256-GCM encrypted. Zero network access. Built for dev teams.",
  alternates: {
    canonical: "/",
  },
  icons: {
    icon: "/favicon.ico",
    apple: "/icon-512.png",
  },
  openGraph: {
    title: "PushKey — Encrypted API Key Vault",
    description: "Your secrets. Encrypted. Where you need them.",
    type: "website",
    images: [{ url: "/icon-512.png", width: 512, height: 512 }],
  },
  twitter: {
    card: "summary",
    title: "PushKey â€” Encrypted API Key Vault",
    description: "Local-first API key vault with encrypted backup, rotation health, and safe .env injection.",
    images: ["/icon-512.png"],
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        <RootProvider>{children}</RootProvider>
      </body>
    </html>
  )
}
