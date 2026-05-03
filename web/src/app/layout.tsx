import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
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
  title: "PushKey — Encrypted API Key Vault",
  description: "Store, rotate, and inject your API secrets into every project automatically. AES-256-GCM encrypted. Zero network access. Built for dev teams.",
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
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  )
}
